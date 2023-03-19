import datetime
import os
import signal
import subprocess
import sys
import logging

from autobisect.common import setup_workspace_for_bisection, load_reproducers, load_status, write_status, load_data

stop = False

experiment_name = "bisection"

workspace_folder = "../workspace"

def bisect(repro_folder, baseline_config,
           kernel_repo, kernel_branch, kernel_commit,
           syzkaller_repository, syzkaller_branch, syzkaller_commit):
    logging.info("Setting up workspace for bisection...")
    signal.signal(signal.SIGINT, signal_handler)
    basedir = os.path.join(repro_folder, experiment_name)
    datadir = os.path.join(basedir, "..")
    crashdir = os.path.join(basedir, "crashes")
    os.makedirs(crashdir, exist_ok=True)
    workdir = os.path.join(basedir, "workdir")
    os.makedirs(workdir, exist_ok=True)
    vm_cfg_file = os.path.join(basedir, "vm.cfg")
    setup_workspace_for_bisection(basedir, crashdir, baseline_config, vm_cfg_file, workdir, kernel_repo, kernel_branch,
                                  syzkaller_repository, syzkaller_branch, datadir)

    command = [workspace_folder + "/syzkaller/bin/syz-bisect", "-crash", crashdir, "-config", vm_cfg_file, "-kernel_commit", kernel_commit,
               "-syzkaller_commit", syzkaller_commit, "-vv", "1000"]

    logging.info("Running command: " + " ".join(command))
    output = ""
    with open(os.path.join(basedir, "auto-bisect.log"), "w+") as bisect_log, \
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:

        # Write output to log file and stdout
        for line in proc.stdout:
            output += line.decode("utf-8")
            sys.stdout.buffer.write(line)
            bisect_log.write(line.decode("utf-8"))
            bisect_log.flush()
            os.fsync(bisect_log.fileno())

    if proc.returncode == 0:
        logging.info("Bisection completed successfully")
        return "OK"
    else:
        if "error: syzkaller build failed: failed to run [\"make\"" in output:
            logging.info("Bisection failed because syzkaller build failed")
            return "Syzkaller build failed (old version?)"
        elif "fatal: reference is not a tree:" in output:
            logging.info("Bisection failed because of invalid kernel commit")
            return "Unreachable kernel commit"
        elif "bisection failed: the crash wasn't reproduced on the original commit" in output:
            logging.info("Bisection failed because the crash wasn't reproduced on the original commit")
            return "Crash not reproducible"
        elif "bisection failed:" in output:
            logging.info("Bisection failed because of other error")
            return "Bisection other"
        else:
            logging.info("Bisection failed because of unknown reason")
            return "Internal other"

def sort_function(x):
    if "similarity" in x:
        return x["similarity"]
    else:
        return 0


def start(args):
    logging.info("Starting bisection")
    start_time = datetime.datetime.now()
    repro_dir = args.reproducer_dir
    # reproducers = filter_reproducers(args)
    reproducers = load_reproducers(args.reproducer_dir, experiment_name, args, filter_reproducers)

    reproducers.sort(
        key=sort_function,
        reverse=True)

    for repro in reproducers:
        directory = repro["data"]["id"]
        try:
            run_bisection(args, directory, repro_dir)
        except Exception as e:
            logging.info("Bisection failed, skipping:")
            logging.info(e)
        global stop
        if stop:
            break
    logging.info("Bisection finished at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Total time: " +
          str(datetime.datetime.now() - start_time) + ")")


def run_bisection(args, directory, repro_dir):
    start_time_reproducer = datetime.datetime.now()
    logging.info("Bisection for " + directory + " started at " + start_time_reproducer.strftime("%Y-%m-%d %H:%M:%S"))
    repro_folder = os.path.join(repro_dir, directory)
    status = load_status(repro_folder, experiment_name)
    data = load_data(repro_folder)
    status["retest_state"] = "running"
    status["reason"] = ""
    write_status(repro_folder, experiment_name, status)
    reason = bisect(repro_folder, args.baseline_config, args.kernel_repository,
                    args.kernel_branch,
                    data["kernel-source-commit"], args.syzkaller_repository, args.syzkaller_branch,
                    data["syzkaller-commit"])
    status = load_status(repro_folder, experiment_name)
    if reason == "OK":
        status["retest_state"] = "done"
        result_str = " succeeded at "
    else:
        status["retest_state"] = "failed"
        status["reason"] = reason
        result_str = " failed at "
    status["retest_date"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_status(repro_folder, experiment_name, status)
    logging.info("Bisection for " + directory + result_str + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
          " (Total time: " + str(datetime.datetime.now() - start_time_reproducer) + ")")


def filter_reproducers(data, reproducer_status):
    # Skip if syzkaller-crash time is older than 2020/06/01
    oldest_date = datetime.datetime(2020, 6, 1)
    if datetime.datetime.strptime(data["syzkaller-crash"]["time"], "%Y/%m/%d %H:%M") < oldest_date:
        logging.info("Skipping " + data["id"] + " because syzkaller-crash time is older than 2020/06/01")
        reproducer_status["retest_state"] = "skipped"
        reproducer_status["reason"] = "syzkaller-crash too old"
        return False
    return True


def signal_handler(sig, frame):
    global stop
    if stop:
        logging.info("Forcing exit\n")
        sys.exit(0)
    else:
        logging.info('You pressed Ctrl+C, stopping after current bisection is done\n')
        stop = True
        # Prevent stop of subprocesses
        signal.signal(signal.SIGINT, signal.SIG_IGN)
