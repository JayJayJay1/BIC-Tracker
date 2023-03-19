import os
import json
import subprocess
import dateparser
import logging

pyszz_path = "../workspace/szz/pyszz"
repos_path = "."

def run_szz(repro_path, reproducerid, fix_commit_hashes, earliest_crash_date=None):
    # pyszz_algorithms = ["agszz", "bszz", "lszz", "maszz", "raszz", "rszz"]
    pyszz_algorithms = ["agszz", "bszz", "lszz", "maszz", "rszz"]
    vszz_algorithms = ["agszz", "bszz", "lszz", "maszz", "pdszz", "raszz", "rszz"]
    os.makedirs(repro_path + "/" + reproducerid + "/szz", exist_ok=True)

    bugfix_commits = []
    for fix_commit_hash in fix_commit_hashes:
        bugfix_commit = {}
        bugfix_commit["repo_name"] = "linux"
        bugfix_commit["fix_commit_hash"] = fix_commit_hash
        # earliest_issue_date is the date of the earliest crash
        if earliest_crash_date is not None:
            bugfix_commit["earliest_issue_date"] = earliest_crash_date
        bugfix_commits.append(bugfix_commit)

    with open(repro_path + "/" + reproducerid + "/szz/bug-fixes.json", "w") as f:
        json.dump(bugfix_commits, f)
    
    if os.path.exists(os.path.join(repro_path, reproducerid, "szz", "status.json")):
        result_json = json.load(open(os.path.join(repro_path, reproducerid, "szz", "status.json"), "r"))
    else:
        result_json = {}

    for algorithm in pyszz_algorithms:
        result_json[algorithm] = {}
        conf_file = pyszz_path + "/conf/" + algorithm + ".yml"
        result_file = repro_path + "/" + reproducerid + "/szz/" + algorithm + "_results.json"

        # pyszz_main(repro_path + "/" + reproducerid + "/szz/bug-fixes.json", repro_path + "/" + reproducerid + "/szz_results.json", conf, "../szz-repositories")
        command = ["python3", pyszz_path + "/main.py", repro_path + "/" + reproducerid + "/szz/bug-fixes.json", conf_file, repos_path, result_file]
        logging.info("Starting szz with command: " + str(command))
        with open(os.path.join(repro_path + "/" + reproducerid + "/szz/", algorithm + ".log"), "w+") as log,\
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
            # Write output to log file
            for line in proc.stdout:
                log.write(line.decode("utf-8"))
                log.flush()
                os.fsync(log.fileno())

        if not os.path.exists(result_file):
            logging.info(algorithm + ": no output produced for reproducer " + reproducerid)
            result_json[algorithm]["inducing_commit_hash"] = "no_output"
        else:
            with open(result_file, "r") as szz_results_file:
                szz_results = json.load(szz_results_file)[0]
                if "inducing_commit_hash" in szz_results and len(szz_results["inducing_commit_hash"]) != 0:
                    logging.info(algorithm + " success.")
                    result_json[algorithm] = szz_results
                else:
                    logging.info(algorithm + " ran successfully, but no inducing commit found.")
                    result_json[algorithm]["inducing_commit_hash"] = "no_inducing_commit"
            
        if proc.returncode != 0:
            logging.info(algorithm + " returned code " + str(proc.returncode))
            result_json[algorithm]["result"] = "failed"
        else:
            logging.info(algorithm + " returned success.")
            result_json[algorithm]["result"] = "success"
    return result_json


def start(args):
    repro_path = args.reproducer_dir
    logging.info("start")
    logging.info(repro_path)
    reproducers = []
    i = 0
    dirs = os.listdir(repro_path)
    total = len(dirs)
    for directory in dirs:
        with open(os.path.join(repro_path, directory, "status.json"), "r") as status_file:
            status = json.load(status_file)
        
        force = True
        if not force and os.path.exists(os.path.join(repro_path, directory, "szz_results.json")):
            continue

        if "fix-commits" in status:
            logging.info(f"[{i}/{total}] Running SZZ for reproducer {directory}")
            earliest_crash_date = None
            for crash in status["crashes"]:
                crash_time = dateparser.parse(crash["time"])
                if earliest_crash_date is None or crash_time < earliest_crash_date:
                    earliest_crash_date = crash_time
            
            earliest_crash_date = earliest_crash_date.strftime("%Y-%m-%dT%H:%M:%S")
            result = run_szz(repro_path, directory, status["fix-commits"], earliest_crash_date)
            with open(os.path.join(repro_path, directory, "szz_results.json"), "w") as szz_results_file:
                json.dump(result, szz_results_file, indent=4)
        else:
            logging.info(f"[{i}/{total}] No fix-commit for {directory}, skipping")
            continue
        i += 1