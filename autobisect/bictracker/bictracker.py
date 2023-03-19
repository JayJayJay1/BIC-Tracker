import operator
import re
import datetime
import shutil
import signal
import sys
import traceback
import itertools
import git
import os
import logging
import csv
from autobisect.autobisect import CustomFormatter

from autobisect.bisector.test_single import reproduce_crash
from autobisect.common import load_reproducers, load_status, load_data, write_status, write_status_path

exampleReproducer = {
    "reproducerCode": "reproducerCode",
    "config": "config",
    "syzkallerCommit": "syzkallerCommit",
    "reproducerOptions": "reproducerOptions"
}

different_crash_tresh_hold = 0.5  # tuned

max_num_tests = 8

INVALID = -1
GOOD = -2

# Dir structure:
# reproducers
# 	- reproducer
# 		- status.json (contains all information about the crash, independently of algorithm)
# 		- repro.c
# 		- repro.syz
# 		- syz-bisect.log
# 		- szz
# 		  - szz_results, logs, etc
# 		  - ...
# 		- autobisect
# 		  - auto-bisect.log
# 		  - crashes
# 		  - configs, vm.cfg
# 		  - workdir
# 		- BIC-Trackerer
# 		  - BIC-Trackerer.log
# 		  - cache
# 		  - status.json
# 	- ...

experiment_name = "bictracker"
earliest_bad = None
result_cache = {}

stop = False

original_crash = None
syzbot_crash = None

summary = ""
warnings = 0

version = "0.5"


def start(args):
    logging.info("Starting BIC-Tracker version " + version)
    signal.signal(signal.SIGINT, signal_handler)
    start_time = datetime.datetime.now()
    reproducers = load_reproducers(args.reproducer_dir, experiment_name, args)

    # Sort by similarity and then by time (newer first)
    reproducers.sort(
        key=lambda x: (
            x["data"]["similarity"],
            datetime.datetime.strptime(x["data"]["syzkaller-crash"]["time"], "%Y/%m/%d %H:%M")),
        reverse=True)

    for reproducer in reproducers:
        directory = os.path.join(args.reproducer_dir, reproducer["data"]["id"])
        bic_track(args, directory,
                  "c5f4546593e9911800f0926c1090959b58bc5c93", reproducer)
        global stop
        if stop:
            break
    logging.info("BIC-Tracker finished at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Total time: " +
                 str(datetime.datetime.now() - start_time) + ")")


def bic_track(args, reproducer_directory, min_good, reproducer):
    rootLogger = logging.getLogger()

    logpath = os.path.join(reproducer_directory,
                           experiment_name, "bic-tracker.log")
    fileh = logging.FileHandler(logpath)
    fileh.setFormatter(CustomFormatter())
    rootLogger.addHandler(fileh)

    start_time = datetime.datetime.now()
    logging.info("===============================================")
    logging.info("BIC-Tracker on reproducer " + reproducer["data"]["id"] + " started at " + start_time.strftime(
        "%Y-%m-%d %H:%M:%S") + ", writing to " + logpath)
    status = load_status(reproducer_directory, experiment_name)
    status["retest_state"] = "running"
    status["reason"] = ""
    write_status(reproducer_directory, experiment_name, status)

    global syzbot_crash
    global summary
    summary = ""
    repo = git.Repo(args.linux)

    status = run_bictracker(args, reproducer_directory,
                            min_good, reproducer, repo)
    global warnings
    status["warnings"] = str(warnings)
    status["version"] = version
    print("Summary:")
    print(summary)

    status["retest_date"] = datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    write_status(reproducer_directory, experiment_name, status)
    logging.info(
        "BIC-Tracker on reproducer " + reproducer["data"]["id"] + " finished with status " + str(
            status) + " at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Total time: " + str(
            datetime.datetime.now() - start_time) + ")")
    logging.info("Cleaning up...")
    cleanup(reproducer_directory)
    rootLogger.removeHandler(fileh)


def cleanup(reproducer_directory):
    for file in os.listdir(os.path.join(reproducer_directory, experiment_name, "traces")):
        if os.path.isdir(os.path.join(reproducer_directory, experiment_name, "traces", file, "workdir")):
            shutil.rmtree(os.path.join(reproducer_directory,
                                       experiment_name, "traces", file, "workdir"))


def run_bictracker(args, reproducer_directory, min_good, reproducer, repo):
    try:
        logging.info("Trying to reproduce on original commit: " +
                     reproducer["data"]["kernel-source-commit"])

        global summary
        global original_crash
        global result_cache
        original_crash = reproducer["data"]["kernel-source-commit"]
        # TODO: set basic crash info
        result_cache[original_crash] = {}

        summary += "> test original commit " + \
            reproducer["data"]["kernel-source-commit"] + "\n"
        test(args, reproducer_directory, reproducer,
             reproducer["data"]["kernel-source-commit"])
        verdict = analyze_results(
            args, reproducer_directory, reproducer["data"]["kernel-source-commit"])
        summary += "=> " + verdict_str(verdict) + "\n"

        if verdict == INVALID or verdict == GOOD:
            summary += "> Return as szz should be executed instead.\n"
            return {
                "retest_state": "delayed",
                "reason": "Crash could not be reproduced on original commit as verdict was " +
                          "invalid" if verdict == INVALID else "good"
            }

        global earliest_bad
        global warnings
        earliest_bad = original_crash

        last_good_major = get_last_good_major(
            args, repo, reproducer_directory, min_good, reproducer)

        if min_good == last_good_major:
            summary += "> Return as crash happens on all tested versions.\n"
            return {
                "retest_state": "delayed",
                "reason": "Crash happens on all tested versions"
            }
        # Print number of commits between last good and earliest bad
        logging.info("Number of commits between last good and earliest bad: " + str(
            len(list(repo.iter_commits(last_good_major + ".." + earliest_bad)))))

        executed_files = []
        if earliest_bad in result_cache and "traces" in result_cache[earliest_bad] and result_cache[earliest_bad]["traces"] is not None:
            executed_files = get_executed_files(
                result_cache[earliest_bad]["traces"])
            # Print number of commits between last good and earliest bad which changed the files executed by the reproducer
            logging.info("Number of commits between last good and earliest bad which changed the files executed by the reproducer: " + str(
                len(list(repo.iter_commits(last_good_major + ".." + earliest_bad, paths=executed_files)))))
        else:
            logging.error(
                "Traces not available for earliest bad commit " + earliest_bad)
            warnings += 1

        candidate_list = bisect(
            args, reproducer_directory, last_good_major, reproducer, executed_files)

        if len(candidate_list) == 0:
            summary += "> Return as too many skips.\n"
            return {
                "retest_state": "delayed",
                "reason": "Too many skips"
            }

        summary += "> Candidate list: " + str(candidate_list) + "\n"
        culprit = select_culprit(args, repo, candidate_list)

        logging.info(
            "BIC-Tracker completed! Culprit: " + str(culprit) + " out of candidate list: " + str(candidate_list))

        summary += "> Return culprit " + str(culprit) + "."
        return {
            "retest_state": "done",
            "culprit": str(culprit)
        }

    except Exception as e:
        logging.error("Exception: " + str(e))
        warnings += 1
        summary += "> Exception: " + str(e) + "\n"
        traceback.print_exc()
        return {
            "retest_state": "failed",
            "reason": str(type(e))
        }


def verdict_str(verdict):
    if verdict == INVALID:
        return "INVALID"
    elif verdict == GOOD:
        return "GOOD"
    else:
        return str(verdict)


def get_last_good_major(args, repo, directory, min_good, reproducer):
    global summary
    # get major version of bad commit
    tags_before = get_tags_before(
        repo, reproducer["data"]["kernel-source-commit"], min_good)

    if len(tags_before) == 0:
        summary += "> Return as no tags before bad commit.\n"
        return ["v5.0"]

    "> Search last good major\n"
    for tag in tags_before:
        commit = repo.git.rev_parse(tag)
        summary += ">> Test " + tag + "\n"
        logging.info("Testing " + tag + " (" + commit + ")")
        test(args, directory, reproducer, commit)
        # reproduce_crash(directory, args.baseline_config,
        #                 args.kernel_repository, args.kernel_branch, commit,
        #                 args.syzkaller_repository, args.syzkaller_branch, reproducer["data"]["syzkaller-commit"])
        verdict = analyze_results(args, directory, commit)
        summary += "=> verdict: " + verdict_str(verdict) + "\n"
        if verdict == GOOD:
            return tag
    return min_good


tag_re = re.compile(r"^v(\d+)\.(\d+)$")


def get_tags_before(repo, commit, min_good):
    # only include tags in the format v4.1
    tags = repo.git.tag("--list", "--contains", min_good,
                        "--no-contains", commit, "--merged", commit, "v*.*")
    tags = tags.split("\n")

    # sort matching tags by major and minor version, with the highest version first
    tags = [tag for tag in tags if tag_re.match(tag)]
    tags = sorted(tags, key=lambda tag: [
                  int(x) for x in tag_re.match(tag).groups()], reverse=True)
    logging.info("Tags before commit: " + str(tags))
    return tags


ok_string = "ok_{}.txt"
invalid_string = "invalid_{}.csv"
trace_string = "trace_{}_{}.csv"
crashtrace_string = "crashtrace_{}.csv"
crash_info_string = "crash_info_{}.csv"


def read_result(args, i, files, traces_directory):
    if trace_string.format(i, 0) in files:
        traces = []
        for j in range(0, max_num_tests):
            if trace_string.format(i, j) in files:
                traces += parse_trace(args, os.path.join(
                    traces_directory, trace_string.format(i, j)))
    else:
        traces = None
    if crashtrace_string.format(i) in files:
        crashtrace = parse_trace(args, os.path.join(
            traces_directory, crashtrace_string.format(i)))
    else:
        crashtrace = None
    if crash_info_string.format(i) in files:
        crash_info = parse_crash_info(os.path.join(
            traces_directory, crash_info_string.format(i)))
    else:
        crash_info = None

    if crash_info is not None and crashtrace is not None:
        return {
            "index": i,
            "traces": traces,
            "crashtrace": crashtrace,
            "crash_info": crash_info,
            "crashed": True,
            "valid": True,
        }
    elif ok_string.format(i) in files:
        return {
            "index": i,
            "crashed": False,
            "valid": True,
        }
    elif invalid_string.format(i) in files:
        invalid_content = open(os.path.join(
            traces_directory, invalid_string.format(i)), "r").read()
        return {
            "index": i,
            "invalid_content": invalid_content,
            "crashed": False,
            "valid": False,
        }
    else:
        return {
            "index": i,
            "traces": traces,
            "crashtrace": crashtrace,
            "crash_info": crash_info,
            "valid": False,
        }


def to_ranges(sorted_list_of_integers):
    ranges = []
    for k, g in itertools.groupby(enumerate(sorted_list_of_integers), lambda x: x[0] - x[1]):
        group = list(map(operator.itemgetter(1), g))
        ranges.append((group[0], group[-1]))
    return ranges


def ranges_to_str(ranges):
    ranges_str = ""
    for range in ranges:
        if range[0] == range[1]:
            ranges_str += str(range[0]) + ", "
        else:
            ranges_str += str(range[0]) + "-" + \
                str(range[1]) + ", "
    return ranges_str[:-2]


def read_results(args, traces_directory):
    global summary
    global warnings
    files = os.listdir(traces_directory)

    missing_traces = []
    missing_crashtraces = []
    missing_crash_info = []

    results = []
    for i in range(max_num_tests):
        result = read_result(args, i, files, traces_directory)
        results.append(result)
        if "crashed" in result and result["crashed"]:
            if "traces" not in result or result["traces"] is None:
                missing_traces.append(i)
            if "crashtrace" not in result or result["crashtrace"] is None:
                missing_crashtraces.append(i)
            if "crash_info" not in result or result["crash_info"] is None:
                missing_crash_info.append(i)

    if len(missing_traces) > 0 or len(missing_crashtraces) > 0 or len(missing_crash_info) > 0:
        missing_files_str = ""
        if len(missing_traces) > 0:
            missing_files_str += "Traces " + \
                ranges_to_str(to_ranges(missing_traces)) + ", "
        if len(missing_crashtraces) > 0:
            missing_files_str += "Crashtraces " + \
                ranges_to_str(to_ranges(missing_crashtraces)) + ", "
        if len(missing_crash_info) > 0:
            missing_files_str += "Crash info " + \
                ranges_to_str(to_ranges(missing_crash_info))

        logging.error("Missing: " + missing_files_str)
        summary += "! Missing: " + missing_files_str + "\n"
        warnings += 1

    return results


# returns either INVALID or the chance that the crash triggered is the same
def analyze_results(args, directory, commit):
    global summary
    global warnings
    traces_directory = os.path.join(
        directory, experiment_name, "traces", commit)

    results = []

    if not os.path.exists(traces_directory):
        logging.error("Traces directory " +
                      traces_directory + " does not exist!")
        warnings += 1
        return INVALID

    results = read_results(args, traces_directory)

    valid = [result for result in results if result["valid"]]
    if len(valid) == 0:
        return INVALID

    # if not enough valids, more runs can be triggered or INVALID could be returned

    scores = []
    max_score = 0
    max_score_result = None
    invalid_scores = []
    for i, result in enumerate(results):
        if result["crashed"]:
            score = analyze_traces(result)
            if score is None:
                invalid_scores.append(i)
                score = 1
            scores.append(score)

            if score > different_crash_tresh_hold and score > max_score:
                max_score = score
                max_score_result = result

    if len(invalid_scores) != 0:
        invalid_ranges_str = ""
        invalid_ranges = to_ranges(invalid_scores)
        for invalid_range in invalid_ranges:
            if invalid_range[0] == invalid_range[1]:
                invalid_ranges_str += str(invalid_range[0]) + ", "
            else:
                invalid_ranges_str += str(invalid_range[0]) + "-" + \
                    str(invalid_range[1]) + ", "
        invalid_ranges_str = invalid_ranges_str[:-2]
        logging.error("Replaced scores: " + invalid_ranges_str)
        warnings += 1
        summary += "! Replaced scores: " + invalid_ranges_str + "\n"

    global result_cache
    if len(scores) == 0:
        result_cache[commit] = {}
        return GOOD
    else:
        result_cache[commit] = max_score_result
        return max(scores)


def parse_trace(args, filename):
    global warnings
    traces = []
    # parse csv file
    with open(filename, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if row[3] != "true" and row[3] != "false":
                logging.error("Invalid inline value in trace file " + filename)
                warnings += 1
                continue
            file = row[0]
            # remove prefix
            if file.startswith(args.linux + "/./"):
                file = file[len(args.linux + "/./"):]
            elif file.startswith(args.linux + "/"):
                file = file[len(args.linux + "/"):]
            else:
                logging.error("Filename " + file + " does not start with prefix")
                warnings += 1
            traces.append({
                "file": row[0],
                "function": row[1],
                "line": row[2],
                "inline": row[3] == "true",
            })
    return traces


def parse_crash_info(filename):
    crash_info = {}
    with open(filename, "r") as f:
        crash_info["crash_title"] = f.readline().strip()
        crash_info["crash_category"] = f.readline().strip()
        crash_info["alternative_titles"] = []
        titles = f.readline().strip()[1:-1]
        titles = titles.split(",")
        for title in titles:
            crash_info["alternative_titles"].append(title.strip())
    return crash_info


def analyze_traces(result):
    global result_cache
    global original_crash
    crash = result_cache[original_crash]

    if "traces" not in crash or "traces" not in result or crash["traces"] is None or result["traces"] is None:
        # TODO
        # trace_intersection_score = None
        return None
    else:
        trace_intersection_score = calc_trace_intersection_score(
            result["traces"], crash["traces"], crash["crashtrace"])
    equal_crash_score = calc_equal_crash_score(
        result["crash_info"], crash["crash_info"])
    crash_location_similarity_score = calc_crash_location_similarity_score(result["crashtrace"],
                                                                           crash["crashtrace"])
    if trace_intersection_score is not None:
        return (trace_intersection_score + equal_crash_score + crash_location_similarity_score) / 3
    else:
        return (equal_crash_score + crash_location_similarity_score) / 2


def get_executed_files(traces):
    return set([trace["file"] for trace in traces])


def calc_trace_intersection_score(suspect_trace, crash_execution_trace, crash_stacktrace):
    functions_suspect_trace = set([trace["function"]
                                  for trace in suspect_trace])
    functions_crash_trace = set([trace["function"]
                                for trace in crash_execution_trace])
    functions_stacktrace = set([trace["function"]
                               for trace in crash_stacktrace])
    intersection_functions = functions_suspect_trace.intersection(
        functions_crash_trace)
    intersection_functions_stacktrace = functions_suspect_trace.intersection(
        functions_stacktrace)

    files_suspect_trace = get_executed_files(suspect_trace)
    files_crash_trace = get_executed_files(crash_execution_trace)
    files_stacktrace = get_executed_files(crash_stacktrace)
    intersection_files = files_suspect_trace.intersection(files_crash_trace)
    intersection_files_stacktrace = files_suspect_trace.intersection(
        files_stacktrace)

    function_score = len(intersection_functions) / len(functions_crash_trace)
    file_score = len(intersection_files) / len(files_crash_trace)
    function_score_stacktrace = len(
        intersection_functions_stacktrace) / len(functions_stacktrace)
    file_score_stacktrace = len(
        intersection_files_stacktrace) / len(files_stacktrace)

    return (function_score + file_score + function_score_stacktrace + file_score_stacktrace) / 4


# equal crash / equal crash category
def calc_equal_crash_score(crash_info_suspect, crash_info_crash):
    titles_suspect = crash_info_suspect["alternative_titles"]
    titles_suspect.append(crash_info_suspect["crash_title"])
    titles_crash = crash_info_crash["alternative_titles"]
    titles_crash.append(crash_info_crash["crash_title"])

    equal_title_score = 1 if len(
        set(titles_suspect).intersection(set(titles_crash))) != 0 else 0
    if crash_info_suspect["crash_category"] == "UNKNOWN" or crash_info_crash["crash_category"] == "UNKNOWN":
        if crash_info_suspect["crash_category"] == crash_info_crash["crash_category"]:
            equal_category_score = 0.25
        else:
            equal_category_score = 0
    else:
        if crash_info_suspect["crash_category"] == crash_info_crash["crash_category"]:
            equal_category_score = 1
        else:
            equal_category_score = 0

    return (equal_title_score + equal_category_score) / 2


def calc_crash_location_similarity_score(crash_stacktrace_suspect, crash_stacktrace_crash):
    # TODO maybe check the function mentioned in the title?
    # TODO put higher weight on the where the error was triggerd
    functions_stacktrace_suspect = set(
        [trace["function"] for trace in crash_stacktrace_suspect])
    functions_stacktrace_crash = set(
        [trace["function"] for trace in crash_stacktrace_crash])
    intersection_functions = set(functions_stacktrace_suspect).intersection(
        set(functions_stacktrace_crash))

    return len(intersection_functions) / len(functions_stacktrace_crash)


done_regex = re.compile(
    "([0-9a-f]{40}) is the first bad commit",
    re.MULTILINE)
bisecting_regex = re.compile(
    r"Bisecting: ([0-9]+) revisions? left to test after this \(roughly [0-9]+ steps?\)\n\[([0-9a-f]{40})\] .*",
    re.MULTILINE)
multi_commit_regex = re.compile(
    "There are only 'skip'ped commits left to test.\nThe first bad commit could be any of: *\n((?:[0-9a-f]{40}\n)*)",
    re.MULTILINE)


def parse_bisection_output(output):
    logging.info("Parsing bisection output: \"" + output + "\"")
    if re.match(done_regex, output):
        logging.info("=> done")
        return {"status": "done", "commits": [re.match(done_regex, output).group(1)], "revisions_left": 0}
    if re.match(multi_commit_regex, output):
        commits = []
        for commit in re.findall(multi_commit_regex, output):
            commits.append(commit)
        logging.info("=> multi-done")
        return {"status": "done", "commits": commits, "revisions_left": 0}
    if re.match(bisecting_regex, output):
        re_result = re.match(bisecting_regex, output)
        next_commit = re_result.group(2)
        logging.info("=> next commit: " + next_commit)
        return {"status": "bisecting", "next_commit": next_commit, "revisions_left": int(re_result.group(1))}
    raise Exception("Unexpected bisection output: " + output)


def bisect(args, directory, last_good_major, reproducer, executed_files):
    global summary
    logging.info("Starting bisection")
    summary += "> Bisect\n"
    repo = git.Repo(args.linux)
    output = repo.git.bisect("start", "--", *executed_files)
    assert output == ""
    output = repo.git.bisect("good", last_good_major)
    assert output == ""
    output = repo.git.bisect("bad", reproducer["data"]["kernel-source-commit"])

    parsed_output = parse_bisection_output(output)
    assert "next_commit" in parsed_output
    current = parsed_output["next_commit"]
    skip_counter = 0
    tests = 0
    while True:
        if skip_counter > 5:
            if parsed_output["revisions_left"] > 10:
                return []
            else:
                logging.info("Too many skips, skipping rest of bisection")
                output = repo.git.bisect("skip", current)
        else:
            logging.info("================= " + current + " =================")

            test(args, directory, reproducer, current, already_checked_out=True)
            tests += 1
            repo.git.restore(".")

            verdict = analyze_results(args, directory, current)
            summary += ">> Test " + current + \
                " => " + verdict_str(verdict) + "\n"
            try:
                if verdict == INVALID:
                    logging.info("Invalid")
                    skip_counter += 1
                    output = repo.git.bisect("skip", current)
                elif verdict == GOOD:
                    logging.info("No crash")
                    output = repo.git.bisect("good", current)
                elif verdict > different_crash_tresh_hold:
                    logging.info("Same crash")
                    global earliest_bad
                    earliest_bad = current
                    output = repo.git.bisect("bad", current)
                else:
                    logging.info("Probably a different crash, skipping")
                    skip_counter += 1
                    output = repo.git.bisect("skip", current)
            except git.GitCommandError as e:
                try:
                    if re.match(multi_commit_regex, e.stdout):
                        commits = re.findall(multi_commit_regex, e.stdout)[0].splitlines()
                        print("=> multi-done")
                        return {"status": "done", "commits": commits, "revisions_left": 0}
                    elif re.match(multi_commit_regex, e.stderr):
                        commits = re.findall(multi_commit_regex, e.stderr)[0].splitlines()
                        print("=> multi-done")
                        return {"status": "done", "commits": commits, "revisions_left": 0}
                except:
                    logging.error(e)
                    logging.error("Bisection failed")
                    return []



        bisection_output = parse_bisection_output(output)
        if bisection_output["status"] == "done":
            logging.info("Bisection done after " + str(tests) + " tests.")
            return bisection_output["commits"]
        current = bisection_output["next_commit"]


def test(args, repro_folder, reproducer, commit, already_checked_out=False):
    if validate_repro_folder(args, repro_folder, commit) and args.cache:
        logging.info("Using cached results for " + commit + ".")
        return

    start_time_reproducer = datetime.datetime.now()
    logging.info("Reproducing " + commit + " started at " +
                 start_time_reproducer.strftime("%Y-%m-%d %H:%M:%S"))
    commit_folder = os.path.join(
        repro_folder, experiment_name, "traces", commit)

    # Delete old results
    if os.path.exists(commit_folder):
        shutil.rmtree(commit_folder)

    os.makedirs(commit_folder)
    status = load_status(commit_folder)
    data = load_data(repro_folder)
    status["retest_state"] = "running"
    status["reason"] = ""
    write_status_path(commit_folder, status)

    reason = reproduce_crash(commit_folder, args.baseline_config, args.kernel_repository,
                             args.kernel_branch,
                             "commit_already_checked_out" if already_checked_out else commit,
                             args.syzkaller_repository, args.syzkaller_branch,
                             data["syzkaller-commit"], tracedir=commit_folder, print_output=False, datadir=repro_folder)
    status = load_status(commit_folder)
    if reason == "good" or reason == "bad":
        status["retest_state"] = "done"
        status["verdict"] = reason
        result_str = " succeeded at "
    else:
        status["retest_state"] = "failed"
        status["reason"] = reason
        result_str = " failed at "
    status["retest_date"] = datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    write_status_path(commit_folder, status)
    logging.info("Reproducing " + commit + result_str + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
                 " (Total time: " + str(datetime.datetime.now() - start_time_reproducer) + ")")


def validate_repro_folder(args, repro_folder, commit):
    commit_folder = os.path.join(
        repro_folder, experiment_name, "traces", commit)
    status = load_status(commit_folder)

    global warnings
    if status["retest_state"] == "not_retested":
        return False
    if status["retest_state"] == "running" or status["retest_state"] == "failed":
        if status["retest_state"] == "failed" and status["reason"] == "skip":
            logging.info(
                "Commit was skipped, retest_skipped option: " + str(args.retest_skipped))
            return not args.retest_skipped

        logging.warning("Retest state of " + commit + " was " + str(status))
        return False
    if status["retest_state"] == "done":
        files = os.listdir(commit_folder)
        for i in range(max_num_tests):
            if ok_string.format(i) in files:
                continue
            elif invalid_string.format(i) in files:
                continue
            elif trace_string.format(i, 0) in files and crashtrace_string.format(i) in files and crash_info_string.format(
                    i) in files:
                continue
            else:
                trace_present = trace_string.format(i, 0) in files
                crashtrace_present = crashtrace_string.format(i) in files
                crash_info_present = crash_info_string.format(i) in files
                if not trace_present and not crashtrace_present and not crash_info_present:
                    logging.warning("No files for trace " + str(i) +
                                    " in commit " + commit + "! Retesting commit.")
                else:
                    if not trace_present:
                        logging.warning("Missing trace file")
                    if not crashtrace_present:
                        logging.warning("Missing crashtrace file")
                    if not crash_info_present:
                        logging.warning("Missing crash_info file")
                    if crashtrace_present and crash_info_present:
                        return True
                    logging.warning("Retesting commit.")
                return False
        return True
    else:
        raise Exception("Unknown retest_state: " + status["retest_state"])


def extract_commits(output):
    regexp = r"[0-9a-f]{40}"
    return re.findall(regexp, output)


def select_culprit(args, repo, candidate_list):
    max_score = -1
    culprit = None
    for candidate in candidate_list:
        # if fix_commit != None:
        # fix_intersection_score = calc_fix_intersection_score(fix_commit, candidate)
        fix_intersection_score = None

        trace_intersection_score = calc_commit_trace_intersection_score(
            candidate, repo)

        if fix_intersection_score is not None:
            score = (fix_intersection_score + trace_intersection_score) / 2
        else:
            score = trace_intersection_score

        if score > max_score:
            max_score = score
            culprit = candidate

    global summary
    summary += "Culprit: " + str(culprit) + \
        " (score: " + str(max_score) + ")\n"

    return culprit


def calc_commit_trace_intersection_score(commit, repo):
    global warnings
    # get all files which were changed in the commit
    files = repo.git.show("--pretty=", "--name-only", commit).splitlines()

    # get all files which were executed in the last reproducer
    global result_cache
    global earliest_bad
    if earliest_bad is None or earliest_bad not in result_cache:
        raise Exception(
            "No result cache entry for earliest bad " + earliest_bad)
    if "traces" in result_cache[earliest_bad]:
        last_reproducible_traces = result_cache[earliest_bad]["traces"]
    elif "crashtrace" in result_cache[earliest_bad]:
        logging.error("No traces found for earliest bad " +
                      earliest_bad + ", using crashtrace instead.")
        warnings += 1
        last_reproducible_traces = result_cache[earliest_bad]["crashtrace"]
    else:
        raise Exception(
            "No traces or crashtrace found in result cache for earliest bad " + earliest_bad)
    if last_reproducible_traces is None:
        logging.debug("No traces found for earliest bad: " +
                      str(result_cache[earliest_bad]))
        return 0

    last_reproducible_files = [trace_entry["file"]
                               for trace_entry in last_reproducible_traces]

    intersection = set(files).intersection(set(last_reproducible_files))

    return len(intersection)


# def get_last_reproducible(commit):
#     # get last commit that was reproducible
#     commits = [commit for commit in list_dir()]
#
#     # sort by commit age
#     commits.sort(key=lambda x: get_commit_age(x))
#
#     for commit in commits:
#         if is_reproducible(commit):
#             return commit
#
#     raise Exception("No reproducible commit found")

# parameters:
# 	trace intersection 0-100
# 		- stack trace
# 		- pc trace
# 		- original trace / last bad
# 	equal_crash 		   bool
# 	equal_crash_category   bool
# 	equal_crash_location   bool

# optional parameters:
# 	intersects fix 0-100

def signal_handler(sig, frame):
    global stop
    sys.exit(0)
    if stop:
        logging.info("Forcing exit\n")
        sys.exit(0)
    else:
        logging.info(
            'You pressed Ctrl+C, stopping after current bictracking is done\n')
        stop = True
        # Prevent stop of subprocesses
        signal.signal(signal.SIGINT, signal.SIG_IGN)
