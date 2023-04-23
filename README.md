This file contains the implementations for my masters thesis "Combining Static and Dynamic Analysis for Identification of Bug Inducing Changes".

This repository contains the full source code, but a workspace folder with additional dependencies is required to run the code in this repository.

First, install required dependencies:
`sudo apt install make gcc flex bison libncurses-dev libelf-dev libssl-dev`

The workspace folder needs to contain the following directories:

|folder name|description|how to setup|
|---|---|---|
|bisect_bin|contains different compiler versions of gcc for bisection|compilers used by syzbot can be found [here](https://github.com/google/syzkaller/blob/master/docs/linux/setup_ubuntu-host_qemu-vm_x86-64-kernel.md#gcc) or `wget -nv https://storage.googleapis.com/syzkaller/bisect_bin.tar.gz; tar -xvf bisect_bin.tar.gz`|
|image|linux image for manual testing|according to the [syzkaller setup](https://github.com/google/syzkaller/blob/master/docs/linux/setup_ubuntu-host_qemu-vm_x86-64-kernel.md#image) |
|patches|git patches to modify linux repo to print traces|already in this repo (created with patchhelper.py)|
|userspace|required to make linux vm for syzkaller|`cd userspace; debootstrap --include=openssh-server,curl,tar,gcc,libc6-dev,time,strace,sudo,less,psmisc,selinux-utils,policycoreutils,checkpolicy,selinux-policy-default,firmware-atheros,systemd,systemd-sysv --components=main,contrib,non-free stable debian; apt install -y init`|
|configs|default configs for syzkaller|already in this repo|
|syzkaller|instance of syzkaller which runs the bisection|`git clone https://github.com/JayJayJay1/syzkaller-bictracker.git syzkaller; git -C syzkaller checkout custom`|
|syzkaller-changing|instance of syzkaller which is checked out by sykaller during testing of older verions|`git clone https://github.com/google/syzkaller.git syzkaller-changing`|
|go|go home directory|according to (syzkaller repo)[https://github.com/google/syzkaller/blob/master/docs/linux/setup.md#go-and-syzkaller]|
|logs|contains logs of runs|empty|
|reproducers|crawled crash reproducers and current test data|create with `autobisect crawl [...]`
|linux|contains the linux kernel|according to the [syzkaller setup](https://github.com/google/syzkaller/blob/master/docs/linux/setup_ubuntu-host_qemu-vm_x86-64-kernel.md#checkout-linux-kernel-source) 
|szz|contains repositories of szz projects and a linux repository used for running SZZ|`git clone https://github.com/grosa1/pyszz.git`, then clone an additional linux repo into szz/szz-repositories.

`runners` contains examples of how to run bictracker or its different modules.