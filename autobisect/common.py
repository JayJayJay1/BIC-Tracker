import json
import logging
import os
import shutil
import subprocess

workspace_folder = "../workspace"

def load_reproducers(folder, experiment_name, args, filter_function=lambda _1, _2: True):
    logging.info("Loading reproducers from " + folder + "...")
    reproducers = []
    for reprodir in os.listdir(folder):
        full_dir = os.path.join(folder, reprodir)
        if args.reproducer is not None and reprodir not in args.reproducer:
            continue

        data = load_data(full_dir)
        if data is None:
            continue

        status = load_status(full_dir, experiment_name)

        if should_test(args, status) and filter_function(data, status):
            reproducers.append({
                "status": status,
                "data": data,
            })
            write_status(full_dir, experiment_name, status)
    return reproducers


def load_data(repro_folder):
    data_file_path = os.path.join(repro_folder, "status.json")
    with open(data_file_path, "r") as data_file:
        try:
            return json.load(data_file)
        except json.decoder.JSONDecodeError:
            logging.info("Failed to parse status.json with contents: " + data_file.read())
            return None


def load_status(repro_folder, experiment_name=""):
    if experiment_name == "":
        data_file_path = os.path.join(repro_folder, "status.json")
    else:
        data_file_path = os.path.join(repro_folder, experiment_name, "status.json")
    # check if file exists
    if not os.path.isfile(data_file_path):
        return {
            "retest_state": "not_retested",
        }

    with open(data_file_path, "r") as data_file:
        return json.load(data_file)


def write_status(repro_folder, experiment_name, status):
    write_status_path(os.path.join(repro_folder, experiment_name), status)


def write_status_path(path, status):
    status_file_path = os.path.join(path, "status.json")
    os.makedirs(path, exist_ok=True)

    with open(status_file_path, "w+") as status_file:
        json.dump(status, status_file, indent=4)


def should_test(args, status):
    if status["retest_state"] == "not_retested":
        return True
    if args.force:
        logging.info("Forcing retest of reproducer with state " + status["retest_state"])
        return True
    if  status["retest_state"] == "failed":
        logging.info("Retrying failed reproducer...")
        return args.retry_failed
    if status["retest_state"] == "running":
        logging.warn("Reproducer had status 'running', retesting...")
        return True
    if status["retest_state"] == "done":
        return False
    if status["retest_state"] == "delayed":
        return args.retry_failed
    logging.warn("Unknown retest state: " + status["retest_state"])
    return False


def write_vm_config(vm_cfg_file, basedir, crashdir, workdir, kernel_repo, kernel_branch, syzkaller_repository,
                    syzkaller_branch):
    cfg_template_path = workspace_folder  + "/configs/vm_syz-bisect.cfg"
    with open(cfg_template_path) as cfg_template_file:
        cfg_template = cfg_template_file.readlines()

    with open(vm_cfg_file, "w+") as cfg_file:
        for line in cfg_template:
            line = line.replace("REPLACE_KERNEL_REPO", kernel_repo)
            line = line.replace("REPLACE_KERNEL_BRANCH", kernel_branch)
            line = line.replace("REPLACE_BISECT_BIN", os.path.abspath(workspace_folder  + "/bisect_bin"))
            line = line.replace("REPLACE_CCACHE_PATH", "/usr/bin/ccache")
            line = line.replace("REPLACE_SYZKALLER_REPO", syzkaller_repository)
            #            line = line.replace("REPLACE_SYSCTL", os.path.abspath(args.sysctl))
            #            line = line.replace("REPLACE_CMDLINE", os.path.abspath(args.cmdline))
            line = line.replace("REPLACE_WORKDIR", workdir)
            line = line.replace("REPLACE_KERNEL_OBJ", os.path.abspath("linux"))
            line = line.replace("REPLACE_KERNEL_SOURCE", os.path.abspath("linux"))
            line = line.replace("REPLACE_SYZKALLER", os.path.abspath("syzkaller-changing"))
            line = line.replace("REPLACE_KERNEL_CONFIG", os.path.join(basedir, "kernel.config"))
            line = line.replace("REPLACE_KERNEL_BASELINE_CONFIG", os.path.join(basedir, "kernel.baseline_config"))
            line = line.replace("REPLACE_KERNEL", os.path.join(os.path.abspath("linux"), "arch/x86_64/boot/bzImage"))
            line = line.replace("REPLACE_USERSPACE", os.path.abspath(workspace_folder  + "/userspace/debian"))
            line = line.replace("REPLACE_IMAGE", os.path.join("image/stretch.img"))
            line = line.replace("REPLACE_KEY", os.path.join("image/stretch.id_rsa"))
            cfg_file.write(line)
    logging.info("Wrote VM config to " + vm_cfg_file)


def setup_workspace_for_bisection(basedir, crashdir, baseline_config, vm_cfg_file, workdir, kernel_repo, kernel_branch,
                                  syzkaller_repository, syzkaller_branch, datadir):
    write_vm_config(vm_cfg_file, basedir, crashdir, workdir, kernel_repo, kernel_branch, syzkaller_repository,
                    syzkaller_branch)
    # Copy baseline config
    if baseline_config:
        shutil.copyfile(baseline_config, os.path.join(basedir, "kernel.baseline_config"))

    if os.path.isfile(os.path.join(datadir, "kernel.config")):
        shutil.copyfile(os.path.join(datadir, "kernel.config"), os.path.join(basedir, "kernel.config"))
    else:
        logging.warning("No kernel config at " + os.path.join(datadir, "kernel.config") + "!")
    if os.path.isfile(os.path.join(datadir, "repro.cprog")):
        shutil.copyfile(os.path.join(datadir, "repro.cprog"), os.path.join(crashdir, "repro.cprog"))
    if os.path.isfile(os.path.join(datadir, "repro.prog")):
        shutil.copyfile(os.path.join(datadir, "repro.prog"), os.path.join(crashdir, "repro.prog"))
    else:
        logging.warning("No reproducer at " + os.path.join(datadir, "repro.prog") + "!")

    # Move reproducers and copy reproducer options
    shutil.copyfile(workspace_folder  + "configs/repro.opts", os.path.join(crashdir, "repro.opts"))

    if subprocess.run(["git", "checkout", "-f", "master"], cwd="syzkaller-changing").returncode != 0:
        logging.error("Failed to checkout master branch in syzkaller-changing")
        raise Exception("Failed to checkout master branch in syzkaller-changing")
    if subprocess.run(["make", "-s"], cwd="syzkaller-changing").returncode != 0:
        logging.error("Failed to make syzkaller on master")
        raise Exception("Failed to make syzkaller on master")

    logging.info("Workspace setup done.")
