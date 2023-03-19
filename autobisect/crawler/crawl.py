import requests
from bs4 import BeautifulSoup
import json
import os
import logging
import subprocess
import re
import datetime


# Fetches bugs from syzbot and parses them into a json file
def start(args):
    logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
    rootLogger = logging.getLogger()
    currentDate = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if args.log_dir:
        fileHandler = logging.FileHandler(args.log_dir + "/crawl_" + currentDate + ".log")
        fileHandler.setFormatter(logFormatter)
        rootLogger.addHandler(fileHandler)

    if not args.dry and not args.reproducer_dir:
        logging.error("No reproducer directory specified, exiting...")
        return

    logging.info("Fetching bugs from syzbot...")
    URL = "https://syzkaller.appspot.com/upstream/fixed"
    page = rate_limited_get(URL)

    logging.info("Parsing html...")
    bugs = parse_bug_table(page.content)
    bugs_bisect_success = [bug for bug in bugs if should_bisect(bug, args)]

    logging.info(f"Total bugs: {len(bugs)}")

    done = 0
    failed = 0
    untested = 0

    for bug in bugs:
        if bug["json"]["cause-bisect"] == "done":
            done += 1
        elif bug["json"]["cause-bisect"] in ["error", "inconclusive", "unreliable"]:
            failed += 1
        elif bug["json"]["cause-bisect"].strip() == "":
            untested += 1
        else:
            logging.warning(f"Unknown bisect status: {bug['json']['cause-bisect']}")
    logging.info(f"Total bugs bisect done: {done}")
    logging.info(f"Total bugs bisect failed: {failed}")
    logging.info(f"Total bugs bisect untested: {untested}")
    

    logging.info("Fetching bisection logs and crashes...")
    fetch_bisection_logs(bugs_bisect_success)

    bugs_with_bics = fetch_bics(bugs_bisect_success, args)
    bugs_bic_available = [bug for bug in bugs_with_bics if len(bug["json"]["bics"]) > 0]
    bugs_bic_not_available = [bug for bug in bugs_with_bics if len(bug["json"]["bics"]) == 0]
    bugs_young_enough = [bug for bug in bugs_with_bics if is_young_enough(args, bug["json"]["syzkaller-crash"]["syzkaller_commit"])]
    bugs_too_old = [bug for bug in bugs_with_bics if not is_young_enough(args, bug["json"]["syzkaller-crash"]["syzkaller_commit"])]
    bugs_bic_available_and_young_enough = [bug for bug in bugs_bic_available if bug in bugs_young_enough]
    bugs_bic_available_and_too_old = [bug for bug in bugs_bic_available if bug in bugs_too_old]
    bugs_bic_not_available_and_too_old = [bug for bug in bugs_bic_not_available if bug in bugs_too_old]
    bugs_bic_not_available_and_young_enough = [bug for bug in bugs_bic_not_available if bug in bugs_young_enough]

    logging.info(f"Total bugs with bics: {len(bugs_with_bics)}")
    logging.info(f"Total bugs with bics available: {len(bugs_bic_available)}")
    logging.info(f"Total bugs with bics not available: {len(bugs_bic_not_available)}")

    logging.info(f"Total bugs with bics available and young enough: {len(bugs_bic_available_and_young_enough)}")
    logging.info(f"Total bugs with bics available and too old: {len(bugs_bic_available_and_too_old)}")
    logging.info(f"Total bugs with bics not available and too old: {len(bugs_bic_not_available_and_too_old)}")
    logging.info(f"Total bugs with bics not available and young enough: {len(bugs_bic_not_available_and_young_enough)}")
    exit()
    logging.info("Determining bisection parameters...")
    determine_bisection_parameters(bugs_bic_available, args)

    if args.dry:
        logging.info("Dry run, not writing bugs to directory...")
        return

    logging.info("Writing bugs to directory...")
    write_bugs_to_dir(bugs_bic_available, args)


def rate_limited_get(url):
    # time.sleep(0.05)
    return requests.get(url)


def parse_bug_table(content):
    soup = BeautifulSoup(content, "html.parser")

    results = soup.find(class_="list_table")
    job_elems = results.find_all("tr")

    bugs = []

    for job_elem in job_elems:
        if job_elem.find("th"):
            continue

        stats = job_elem.find_all("td", class_="stat")
        bisect_status = job_elem.find_all("td", class_="bisect_status")

        bug = {}
        bug["json"] = {}
        bug_json = bug["json"]
        bug_json["title"] = job_elem.find("td", class_="title").text.strip()
        bug_json["link"] = "https://syzkaller.appspot.com" + job_elem.find("td", class_="title").find("a")["href"]
        bug_json['id'] = bug_json["link"].split("=")[-1]
        bug_json["reproducer"] = stats[0].text.strip()
        bug_json["cause-bisect"] = bisect_status[0].text.strip()
        bug_json["fix-bisect"] = bisect_status[1].text.strip()
        bug_json["count"] = stats[1].text.strip()
        bug_json["last"] = stats[2].text.strip()
        bug_json["reported"] = stats[3].text.strip()
        bug_json["patched"] = job_elem.find("td", class_="patched").text.strip()
        bug_json["closed"] = stats[4].text.strip()
        bug_json["patch"] = job_elem.find("td", class_="commit_list").text.strip()
        bugs.append(bug)

    return bugs


# "reported": "1228d",
# "reported": "1228d07h",
# "reported": "16h10m",

def should_bisect(bug, args):
    if bug["json"]["cause-bisect"] != "done":
        return False
    return True


def fetch_bisection_logs(bugs_bisect_success):
    num_bugs = len(bugs_bisect_success)
    i = 0
    for bug in bugs_bisect_success:
        bug_html = BeautifulSoup(rate_limited_get(bug["json"]["link"]).content, "html.parser")
        link = bug_html.find("a", string="bisect log")
        if link:
            bug["bisect-log"] = rate_limited_get("https://syzkaller.appspot.com" + link["href"]).text
        else:
            logging.warning(f"Bug {bug['json']['id']} has no bisect log")

        fix_commit_text = bug_html.find("b", string="Fix commit:")
        # find all <span class="mono"> elements between <b>"Fix commit:"</b> and <b>"Patched on:"</b> and put them in a list
        bug["json"]["fix-commits"] = []
        for span in fix_commit_text.find_next_siblings("span", class_="mono"):
            if span.find("a"):
                bug["json"]["fix-commits"].append(span.find("a").get("href").split("=")[-1])
            else:
                # this is the title of the commit instead of a link, the commit can probably not be checked out
                text_regex = re.compile(r"[\n\t\s]*(.*)[\n\t\s]*")
                text = re.search(text_regex, span.text).group(1)
                # logging.info(f"Commit title trimmed: {text}")
                bug["json"]["fix-commits"].append(text)
            if span.find_next_sibling().name != "span":
                break

        if bug_html.find("b", string="Fix bisection: fixed by"):
            fix_bisection_commit_text = bug_html.find("b", string="Fix bisection: fixed by").find_next("span",
                                                                                                       class_="mono").text

            # multiline
            regex = re.compile(r"commit ([0-9a-f]{40})", re.MULTILINE)
            fix_bisection_commit_match = re.search(regex, fix_bisection_commit_text)

            if fix_bisection_commit_match:
                fix_bisection_commit = fix_bisection_commit_match.group(1)
                bug["json"]["fix-bisection-commit"] = fix_bisection_commit
                if fix_bisection_commit not in bug["json"]["fix-commits"]:
                    logging.debug(f"Bug {bug['json']['id']} fix commits do not contain fix bisection commit, " + \
                                  f"fix commits: {bug['json']['fix-commits']}, fix bisection commit: {fix_bisection_commit}")
            else:
                logging.warning(f"Bug {bug['json']['id']} no commit in " + fix_bisection_commit_text)

        crash_table = None
        tables = bug_html.find_all("table", class_="list_table")
        for table in tables:
            if table.find("caption"):
                if table.find("caption").text.startswith("Crashes"):
                    crash_table = table
                    break

        if crash_table is None:
            raise Exception(f"Bug {bug['json']['id']} has no crash table")

        syz_reproducer_link = bug_html.find("a", string="syz").get("href")
        links = crash_table.find_all("a", href=syz_reproducer_link)
        if len(links) != 1:
            raise Exception(f"Exception")
        tr_entry = links[0].parent.parent
        bug["json"]["syzkaller-crash"] = extract_json_from_tr(tr_entry)

        bug["json"]["crashes"] = []
        for crash in crash_table.find_all("tr"):
            if crash.find("th"):
                continue

            crash_json = extract_json_from_tr(crash)

            # Ignore crashes without reproducers
            if "reproducer_link" in crash_json or "c-reproducer_link" in crash_json:
                bug["json"]["crashes"].append(crash_json)
        if len(bug["json"]["crashes"]) == 0:
            raise Exception(f"Bug {bug['json']['id']} has no crashes")

        i += 1
        print("[" + "=" * int(i / num_bugs * 20) + " " * (20 - int(i / num_bugs * 20)) + "] " + str(i) + "/" + str(
            num_bugs), end="\r")
    print()


def fetch_bics(bugs, args):
    bics = []
    for bug in bugs:
        for commit in bug["json"]["fix-commits"]:
            is_commit = re.match(r"^[0-9a-f]{40}$", commit)
            if is_commit:
                cmd = f"git -C '{args.linux}' log -1 {commit}"
                commit_message = os.popen(cmd).read()
            else:
                commit = commit.replace("\"", "\\\"")
                cmd = f"git -C '{args.linux}' log -1 --grep=\"{commit}\""
                commit_message = os.popen(cmd).read()
            if "Fixes: " in commit_message:
                bic = commit_message.split("Fixes: ")[1].split(" ")[0][0:12]
                bics.append(bic)
        bug["json"]["bics"] = bics
        bics = []
    return bugs


REQUIRED_COMMIT = "3bcdec13657598f6a6163c7ddecff58c2d3a2a71"


def is_young_enough(args, syzkaller_commit):
    cmd = f"git -C \"{args.syzkaller_dir}\" merge-base --is-ancestor 3bcdec13657598f6a6163c7ddecff58c2d3a2a71 \"{syzkaller_commit}\""
    logging.info("$" + cmd)
    return os.system(cmd) == 0


def determine_bisection_parameters(bugs_bisect_success, args):
    num_bugs = len(bugs_bisect_success)
    i = 0
    for bug in bugs_bisect_success:
        if bug["json"]["syzkaller-crash"]["kernel"] == "upstream":
            logging.info(f"[{bug['json']['id']}]: upstream.")
            resolve_links(bug, bug["json"]["syzkaller-crash"])
            bug["json"]["similarity"] = 100
        else:
            # test if the commit exists on linux-next with git
            # if it does, use that commit

            if bug["json"]["syzkaller-crash"]["kernel"] == "linux-next":
                logging.info(
                    f"[{bug['json']['id']}]: linux-next, checking if commit exists on local linux-next repository...")
                commit = bug["json"]["syzkaller-crash"]["kernel_commit"]
                if subprocess.run(["git", "cat-file", "-e", commit], cwd=args.linux).returncode == 0:
                    print("Commit exists, using it")
                    resolve_links(bug, bug["json"]["syzkaller-crash"])
                    bug["json"]["similarity"] = 100
                    continue
                logging.info("Commit does not exist, using most-similar commit")
            else:
                logging.info(
                    f"[{bug['json']['id']}]: {bug['json']['syzkaller-crash']['kernel']}, using most-similar commit")

            best_crash = 0
            best_crash_score = -1
            for i, crash in enumerate(bug["json"]["crashes"]):
                similarity = 0

                if crash["kernel_commit"] == bug["json"]["syzkaller-crash"]["kernel_commit"]:
                    similarity += 40
                if crash["syzkaller_commit"] == bug["json"]["syzkaller-crash"]["syzkaller_commit"]:
                    similarity += 20
                if crash["kernel"] == "linux-next":
                    commit = crash["kernel_commit"]
                    if subprocess.run(["git", "cat-file", "-e", commit], cwd=args.linux).returncode == 0:
                        if crash["kernel"] == bug["json"]["syzkaller-crash"]["kernel"]:
                            similarity += 30
                    else:
                        logging.info(
                            f"[{bug['json']['id']}]: {crash['kernel_commit']} does not exist on local linux-next repository")
                        continue
                elif crash["kernel"] == "upstream":
                    if crash["kernel"] == bug["json"]["syzkaller-crash"]["kernel"]:
                        similarity += 30

                if similarity > best_crash_score:
                    best_crash_score = similarity
                    best_crash = i
            logging.info(f"Best score: {best_crash_score}")
            bug["json"]["similarity"] = best_crash_score
            resolve_links(bug, bug["json"]["crashes"][best_crash])
        i += 1
        print("[" + "=" * int(i / num_bugs * 20) + " " * (20 - int(i / num_bugs * 20)) + "] " + str(i) + "/" + str(
            num_bugs), end="\r")
    print()


def extract_json_from_tr(crash):
    crash_json = {}
    for i, column in enumerate(crash.find_all("td")):
        if i == 0:
            crash_json["manager"] = column.text.strip()
        elif i == 1:
            crash_json["time"] = column.text.strip()
        elif i == 2:
            crash_json["kernel"] = column.text.strip()
        elif i == 3:
            if column.find("a"):
                crash_json["kernel_commit_link"] = column.find("a")["href"]
                crash_json["kernel_commit"] = crash_json["kernel_commit_link"].split("=")[-1]
            else:
                logging.warning(f"Column {column.text} has no kernel link")
        elif i == 4:
            if column.find("a"):
                crash_json["syzkaller_commit_link"] = column.find("a")["href"]
                crash_json["syzkaller_commit"] = crash_json["syzkaller_commit_link"].split("/")[-1]
            else:
                logging.warning(f"Column {column.text} has no syzkaller link")
        elif i == 5 and column.find("a"):
            crash_json["config_link"] = "https://syzkaller.appspot.com" + column.find("a")["href"]
        elif i == 8 and column.find("a"):
            crash_json["reproducer_link"] = "https://syzkaller.appspot.com" + column.find("a")["href"]
        elif i == 9 and column.find("a"):
            crash_json["c-reproducer_link"] = "https://syzkaller.appspot.com" + column.find("a")["href"]
    return crash_json


def resolve_links(bug, crash):
    bug["json"]["kernel-source-commit"] = crash["kernel_commit"]
    bug["json"]["syzkaller-commit"] = crash["syzkaller_commit"]
    bug["reproducer"] = rate_limited_get(crash["reproducer_link"]).text
    if "c-reproducer_link" in crash:
        bug["c-reproducer"] = rate_limited_get(crash["c-reproducer_link"]).text
    bug["kernel-config"] = rate_limited_get(crash["config_link"]).text


def write_bugs_to_dir(bugs_bisect_success, args):
    num_bugs = len(bugs_bisect_success)
    i = 0
    for bug in bugs_bisect_success:
        dir = args.reproducer_dir + f"/{bug['json']['id']}"
        os.makedirs(dir + "/bisection/crashes", exist_ok=True)
        with open(dir + "/status.json", "w") as f:
            json.dump(bug["json"], f, indent=4)
        if "reproducer" in bug:
            with open(dir + "/repro.prog", "w") as f:
                f.write(bug["reproducer"])
        else:
            logging.warning(f"Bug {bug['json']['id']} has no reproducer")
        if "c-reproducer" in bug:
            with open(dir + "/repro.cprog", "w") as f:
                f.write(bug["c-reproducer"])
        if "kernel-config" in bug:
            with open(dir + "/kernel.config", "w") as f:
                f.write(bug["kernel-config"])
        else:
            logging.warning(f"Bug {bug['json']['id']} has no kernel config")
        if "bisect-log" in bug:
            with open(dir + "/bisection/syz-bisect.log", "w") as f:
                f.write(bug["bisect-log"])
        else:
            logging.warning(f"Bug {bug['json']['id']} has no bisect log")
        i += 1
        print("[" + "=" * int(i / num_bugs * 20) + " " * (20 - int(i / num_bugs * 20)) + "] " + str(i) + "/" + str(
            num_bugs), end="\r")

# Can be removed?
# logging.info("Fetching bug data...")
# for bug in bugs_bisect_success:
#     bug["json"]["data"] = rate_limited_get(bug["json"]["link"] + "&json=1").json()

# logging.info("Fetching bug reproducers and config...")
# for bug in bugs_bisect_success:
#     if "syz-reproducer" in bug["json"]["data"]["crashes"][0]:
#         bug["reproducer"] = rate_limited_get("https://syzkaller.appspot.com" + bug["json"]["data"]["crashes"][0]["syz-reproducer"]).text
#     else:
#         logging.warning(f"Bug {bug['json']['id']} has no syz-reproducer")
#     if "c-reproducer" in bug["json"]["data"]["crashes"][0]:
#         bug["c-reproducer"] = rate_limited_get("https://syzkaller.appspot.com" + bug["json"]["data"]["crashes"][0]["c-reproducer"]).text
#     if "kernel-config" in bug["json"]["data"]["crashes"][0]:
#         bug["kernel-config"] = rate_limited_get("https://syzkaller.appspot.com" + bug["json"]["data"]["crashes"][0]["kernel-config"]).text
#     else:
#         logging.warning(f"Bug {bug['json']['id']} has no kernel config")
#     if bug["json"]["data"]["crashes"][0]["kernel-source-commit"]:
#         bug["json"]["kernel-source-commit"] = bug["json"]["data"]["crashes"][0]["kernel-source-commit"]
#     else:
#         logging.info(f"Bug {bug['json']['id']} has no kernel source commit")
#     if bug["json"]["data"]["crashes"][0]["syzkaller-commit"]:
#         bug["json"]["syzkaller-commit"] = bug["json"]["data"]["crashes"][0]["syzkaller-commit"]
#     else:
#         logging.warning(f"Bug {bug['json']['id']} has no syzkaller commit")
