import datetime
import os
import signal
import subprocess
import sys
import logging
import git
import shutil
import json
from autobisect.common import setup_workspace_for_bisection, load_reproducers, load_status, write_status, load_data

experiment_name = "reproduce_original"

stop = False

workspace_folder = "../workspace"

def reproduce_crash(basedir, baseline_config,
                    kernel_repo, kernel_branch, kernel_commit,
                    syzkaller_repository, syzkaller_branch, syzkaller_commit, tracedir, print_output=True, datadir=None):
    if datadir is None:
        datadir = os.path.join(basedir, "..")
    
    # Delete old results
    if os.path.exists(tracedir):
        logging.info("Deleting old results...")
        shutil.rmtree(tracedir)

    logging.info("Setting up workspace...")
    os.makedirs(tracedir, exist_ok=True)
    crashdir = os.path.join(basedir, "crashes")
    os.makedirs(crashdir, exist_ok=True)
    workdir = os.path.join(basedir, "workdir")
    os.makedirs(workdir, exist_ok=True)

    vm_cfg_file = os.path.join(basedir, "vm.cfg")
    setup_workspace_for_bisection(basedir, crashdir, baseline_config, vm_cfg_file, workdir, kernel_repo, kernel_branch,
                                  syzkaller_repository, syzkaller_branch, datadir)

    command = [workspace_folder + "/syzkaller/bin/syz-test-single", "-tracedir", tracedir, "-crash", crashdir, "-config", vm_cfg_file,
               "-kernel_commit", kernel_commit, "-syzkaller_commit", syzkaller_commit, "-vv", "1000"]

    logging.info("Running command: " + " ".join(command) + ", output will be written to " + os.path.join(basedir,
                                                                                                         "test-single.log"))
    output = ""
    with open(os.path.join(basedir, "test-single.log"), "w+") as bisect_log, \
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:

        # Write output to log file and stdout
        for line in proc.stdout:
            try:
                output += line.decode("utf-8")
                bisect_log.write(line.decode("utf-8"))
                bisect_log.flush()
                os.fsync(bisect_log.fileno())
            except:
                logging.info("Error while writing output to log file")
                pass
            try:
                if print_output:
                    sys.stdout.buffer.write(line)
                    sys.stdout.flush()
            except:
                logging.info("Error while writing output to stdout")
                pass

    if proc.returncode == 0:
        if "§Verdict is bad§" in output:
            verdict = "bad"
        elif "§Verdict is good§" in output:
            verdict = "good"
        elif "§Verdict is skip§" in output:
            verdict = "skip"
        elif "§Verdict is missing§" in output:
            verdict = "missing"
        else:
            verdict = "unknown"
        logging.info("§+ Single test completed, verdict: " + verdict)
        if verdict == "skip" and syzkaller_commit_is_old("syzkaller-changing", syzkaller_commit):
            logging.info("Verdict is skip, but syzkaller commit is old, so we try again with a newer commit")
            verdict = reproduce_crash(basedir, baseline_config,
                                   kernel_repo, kernel_branch, kernel_commit,
                                   syzkaller_repository, syzkaller_branch, "6d752409f178135881da3510c910bb11ae1f1381", tracedir, print_output, datadir)
            if verdict == "bad":
                try:
                    data = load_data(datadir)
                    logging.info("§+ Single test completed, and verdict was bad, overwriting sykaller commit " + syzkaller_commit + " with 6d752409f178135881da3510c910bb11ae1f1381.")
                    data["syzkaller-commit"] = "6d752409f178135881da3510c910bb11ae1f1381"
                    with open(os.path.join(datadir, "status.json"), "w+") as f:
                        json.dump(data, f, indent=4)
                except Exception as e:
                    logging.error("§+ Single test completed, and verdict was bad, but could not overwrite sykaller commit " + syzkaller_commit + " with 6d752409f178135881da3510c910bb11ae1f1381.")
                    logging.error(e)
        return verdict
    else:
        if "error: syzkaller build failed: failed to run [\"make\"" in output:
            logging.info("§+ Single test failed because syzkaller build failed")
            return "Syzkaller build failed (old version?)"
        elif "fatal: reference is not a tree:" in output:
            logging.info("§+ Single test failed because of invalid kernel commit")
            return "Unreachable kernel commit"
        else:
            logging.info("§+ Single test failed because of unknown reason")
            return "Internal other"


def syzkaller_commit_is_old(syzkaller_repository, syzkaller_commit):
    repo = git.Repo(syzkaller_repository)
    first_fixed_commit = "9d56e7ddd67e5ec46588c6434db739d94a7d2aae"

    # if syzkaller_commit is older than first_fixed_commit, it is old
    return repo.is_ancestor(repo.commit(syzkaller_commit), repo.commit(first_fixed_commit))


def start(args):
    logging.info("Starting reproduce")
    start_time = datetime.datetime.now()
    reproducers = load_reproducers(args.reproducer_dir, experiment_name, args)

    signal.signal(signal.SIGINT, signal_handler)

    # Sort by similarity and then by time (newer first)
    reproducers.sort(
        key=lambda x: (
            x["data"]["similarity"],
            datetime.datetime.strptime(x["data"]["syzkaller-crash"]["time"], "%Y/%m/%d %H:%M")),
        reverse=True)

    for reproducer in reproducers:
        directory = os.path.join(args.reproducer_dir, reproducer["data"]["id"])
        try:
            run_reproduce(args, directory, reproducer)
        except Exception as e:
            logging.info("Reproduce failed:")
            raise e
        global stop
        if stop:
            break
    logging.info(
        "Reproduce finished at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Total time: " +
        str(datetime.datetime.now() - start_time) + ")")


def run_reproduce(args, repro_folder, reproducer):
    start_time_reproducer = datetime.datetime.now()
    data = reproducer["data"]
    logging.info(
        "Reproduce for " + data["id"] + " started at " + start_time_reproducer.strftime("%Y-%m-%d %H:%M:%S"))
    status = load_status(repro_folder, experiment_name)
    data = load_data(repro_folder)
    status["retest_state"] = "running"
    status["reason"] = ""
    write_status(repro_folder, experiment_name, status)

    basedir = os.path.join(repro_folder, experiment_name)
    kernel_commit = data["syzkaller-commit"]
    reason = reproduce_crash(basedir, args.baseline_config, args.kernel_repository,
                             args.kernel_branch,
                             data["kernel-source-commit"], args.syzkaller_repository, args.syzkaller_branch,
                             kernel_commit, tracedir=os.path.join(basedir, "traces/" + kernel_commit))
    status = load_status(repro_folder, experiment_name)
    if reason == "good" or reason == "bad":
        status["retest_state"] = "done"
        status["verdict"] = reason
        result_str = " succeeded at "
    else:
        status["retest_state"] = "failed"
        status["reason"] = reason
        result_str = " failed at "
    status["retest_date"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_status(repro_folder, experiment_name, status)
    logging.info(
        "Reproduce for " + data["id"] + result_str + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
        " (Total time: " + str(datetime.datetime.now() - start_time_reproducer) + ")")


def signal_handler(sig, frame):
    global stop
    if stop:
        logging.info("Forcing exit\n")
        sys.exit(0)
    else:
        logging.info('You pressed Ctrl+C, stopping after current single-test is done\n')
        stop = True
        # Prevent stop of subprocesses
        signal.signal(signal.SIGINT, signal.SIG_IGN)
