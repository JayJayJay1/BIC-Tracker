from flask import Flask, render_template
import os
import json
import datetime

app = Flask(__name__)

basepath = "../workspace"


@app.route('/')
def index():
    reproducers = []
    reproducer_dir = basepath + "/reproducers"
    if not os.path.exists(reproducer_dir):
        log = ""
        if os.path.exists(basepath + "/crawl.log"):
            log = open(basepath + "/crawl.log", "r").read()
        return render_template('loading.html', log=log)

    for directory in os.listdir(reproducer_dir):
        try:
            with open(reproducer_dir + f"/{directory}/status.json", "r") as f:
                repro = json.load(f)
                if repro["retest_state"] != "not_retested":
                    try:
                        with open(reproducer_dir + f"/{directory}/bisection/auto-bisect.log", "r") as f:
                            repro["log"] = f.read()
                            repro["log_info"] = extract_log_info(repro["log"])
                            if repro["log_info"]["compilers"]:
                                repro["compiler_text"] = " ".join(
                                    [f"{compiler}(x{occurence})\n" for compiler, occurence in
                                     repro["log_info"]["compilers"].items()])
                    except Exception as e:
                        repro["log"] = "Error occured while retrieving log: " + repr(e)
                else:
                    repro["log"] = ""
                    repro["log_info"] = {}
                    repro["compiler_text"] = ""

                try:
                    with open(reproducer_dir + f"/{directory}/bisection/syz-bisect.log", "r") as f:
                        repro["syz_log_info"] = extract_log_info(f.read())
                        repro["syz_compiler_text"] = " ".join([f"{compiler}(x{occurence})\n" for compiler, occurence in
                                                               repro["syz_log_info"]["compilers"].items()])
                except Exception as e:
                    repro["syz_log_info"] = {}
                    repro["syz_compiler_text"] = "Error occured while retrieving syz-log: " + repr(e)

                try:
                    with open(reproducer_dir + f"/{directory}/szz_results.json", "r") as f:
                        json_szz = json.load(f)
                        repro["szz_results"] = json_szz
                except Exception as e:
                    repro["szz_results"] = []
                reproducers.append(repro)
        except Exception as e:
            reproducers.append({"id": directory, "title": "Bug could not be loaded (Reason: " + repr(e)})

    reproducers.sort(key=lambda x: (x["similarity"] if "similarity" in x else 0,
                                    datetime.datetime.strptime(x["syzkaller-crash"]["time"],
                                                               "%Y/%m/%d %H:%M") if "syzkaller-crash" in x else datetime.datetime(
                                        1999, 10, 10)), reverse=True)

    total = len(reproducers)
    # count how many with different similarities
    similarity_100 = 0
    similarity_60 = 0
    similarity_20 = 0
    similarity_0 = 0
    similarity_minus_1 = 0

    for repro in reproducers:
        if "similarity" not in repro:
            similarity_minus_1 += 1
        elif repro["similarity"] == 100:
            similarity_100 += 1
        elif repro["similarity"] == 60:
            similarity_60 += 1
        elif repro["similarity"] == 20:
            similarity_20 += 1
        elif repro["similarity"] == 0:
            similarity_0 += 1
        elif repro["similarity"] == -1:
            similarity_minus_1 += 1
        else:
            print("Unknown similarity: " + str(repro["similarity"]))

    stats = f"{similarity_100} ({similarity_100 / total * 100:.2f}%) with same crash, {similarity_60} ({similarity_60 / total * 100:.2f}%) with different crash but same commits, {similarity_20} ({similarity_20 / total * 100:.2f}%) with different kernel commit but same syzkaller commit, {similarity_0} ({similarity_0 / total * 100:.2f}%) with different commits and {similarity_minus_1} ({similarity_minus_1 / total * 100:.2f}%) not reproducible."
    return render_template('autobisect.html', reproducers=reproducers, stats=stats)


def extract_log_info(log):
    info = {}
    info["steps_done"] = 0
    info["compilers"] = {}

    for line in log.splitlines():
        if line.endswith(" is the first bad commit"):
            info["commit"] = line.split(" ")[0]
        elif line.startswith("bisecting cause commit starting from "):
            info["starting_commit"] = line.split(" ")[5]
        elif line.startswith("building syzkaller on "):
            info["syzkaller_commit"] = line.split(" ")[3]
        elif line.startswith("compiler: "):
            compiler = line.split(" ", 1)[1]
            if compiler not in info["compilers"]:
                info["compilers"][compiler] = 1
            else:
                info["compilers"][compiler] += 1
            info["steps_done"] += 1
            # line start with "Bisecting: " and ends with " steps)"
        elif line.startswith("Bisecting: ") and line.endswith(" steps)"):
            info["revisions_left_to_test"] = int(line.split(" ")[1])
            info["estimated_steps_left"] = int(line.split(" ")[-2])

    return info
