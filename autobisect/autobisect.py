#!/usr/bin/env python3

import logging
import argparse
import autobisect.bisector.bisect as bisect
import autobisect.crawler.crawl as crawl
import autobisect.bictracker.bictracker as bictracker
import autobisect.szz.szz as szz
import autobisect.bisector.test_single as testsingle

workspace_folder = "../workspace"

def create_parser():
    parser = argparse.ArgumentParser(
        description='Run bisection on a directory with reproducers')
    subparsers = parser.add_subparsers(help='subcommands', dest='command')

    bisect_parser = subparsers.add_parser(
        'bisect', help='Run bisection on a directory with reproducers')
    bisect_parser.add_argument('--reproducer_dir', default="reproducers.test",
                               required=True, help='Directory with reproducers')
    bisect_parser.add_argument('--baseline_config', required=False,
                               default=workspace_folder + "/syzkaller/dashboard/config/linux/upstream-apparmor-kasan-base.config", help='Baseline configuration')
    bisect_parser.add_argument('--kernel_repository', required=False,
                               default="git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git", help='Kernel git reprository')
    bisect_parser.add_argument('--kernel_branch', required=False,
                               default="master", help='Branch in kernel git reprository')
    bisect_parser.add_argument('--syzkaller_repository', required=False,
                               default="https://github.com/google/syzkaller.git", help='Syzkaller git reprository')
    bisect_parser.add_argument('--syzkaller_branch', required=False,
                               default="HEAD", help='Branch in  git reprository')
    bisect_parser.add_argument('--force', required=False, default=False,
                               action='store_true', help='Retest even if already tested')
    bisect_parser.add_argument(
        '--reproducer', required=False, help='A reproducer to test', action='append')
    bisect_parser.add_argument('--retry_failed', required=False,
                               default=False, action='store_true', help='Retry failed tests')

    bictrack_parser = subparsers.add_parser(
        'bictrack', help='Run bictracker algorithm on a directory with reproducers')
    bictrack_parser.add_argument('--reproducer_dir', default="reproducers.test",
                                 required=True, help='Directory with reproducers')
    bictrack_parser.add_argument('--baseline_config', required=False,
                                 default=workspace_folder + "/syzkaller/dashboard/config/linux/upstream-apparmor-kasan-base.config", help='Baseline configuration')
    bictrack_parser.add_argument('--kernel_repository', required=False,
                                 default="git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git", help='Kernel git reprository')
    bictrack_parser.add_argument('--kernel_branch', required=False,
                                 default="master", help='Branch in kernel git reprository')
    bictrack_parser.add_argument('--syzkaller_repository', required=False,
                                 default="https://github.com/google/syzkaller.git", help='Syzkaller git reprository')
    bictrack_parser.add_argument(
        '--syzkaller_branch', required=False, default="HEAD", help='Branch in  git reprository')
    bictrack_parser.add_argument('--force', required=False, default=False,
                                 action='store_true', help='Retest even if already tested')
    bictrack_parser.add_argument(
        '--reproducer', required=False, help='A reproducer to test', action='append')
    bictrack_parser.add_argument('--retry_failed', required=False,
                                 default=False, action='store_true', help='Retry failed tests')
    bictrack_parser.add_argument('--cache', required=False, default=False,
                                 action='store_true', help='Use chached results if available')
    bictrack_parser.add_argument(
        '--linux', required=True, default="linux", help='Kernel git reprository directory')
    bictrack_parser.add_argument('--retest_skipped', required=False, default=False,
                                 action='store_true', help='Retest commits which were skipped')

    reproduce_parser = subparsers.add_parser(
        'reproduce', help='Only tries to reproduce the bug on the original commit')
    reproduce_parser.add_argument(
        '--reproducer_dir', default="reproducers.test", required=True, help='Directory with reproducers')
    reproduce_parser.add_argument('--baseline_config', required=False,
                                  default=workspace_folder + "/syzkaller/dashboard/config/linux/upstream-apparmor-kasan-base.config", help='Baseline configuration')
    reproduce_parser.add_argument('--kernel_repository', required=False,
                                  default="git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git", help='Kernel git reprository')
    reproduce_parser.add_argument('--kernel_branch', required=False,
                                  default="master", help='Branch in kernel git reprository')
    reproduce_parser.add_argument('--syzkaller_repository', required=False,
                                  default="https://github.com/google/syzkaller.git", help='Syzkaller git reprository')
    reproduce_parser.add_argument(
        '--syzkaller_branch', required=False, default="HEAD", help='Branch in  git reprository')
    reproduce_parser.add_argument('--force', required=False, default=False,
                                  action='store_true', help='Retest even if already tested')
    reproduce_parser.add_argument(
        '--reproducer', required=False, help='The reproducer to test', action='append')
    reproduce_parser.add_argument('--retry_failed', required=False,
                                  default=False, action='store_true', help='Retry failed tests')

    crawl_parser = subparsers.add_parser(
        'crawl', help='Crawl syzbot for reproducers')
    crawl_parser.add_argument('--reproducer_dir', required=False,
                              help='Directory where reproducers shall be stored')
    crawl_parser.add_argument(
        '--syzkaller_dir', required=True, help='Syzkaller repository to check commit age')
    crawl_parser.add_argument(
        '--log_dir', required=False, help='Directory where the log shall be stored')
    crawl_parser.add_argument(
        '--dry', required=False, default=False, action='store_true', help='Dry run')
    crawl_parser.add_argument('--linux', required=True, default="linux",
                              help='Kernel git reprository directory (we need to check if fixes are available in commit messages)')

    szz_parser = subparsers.add_parser(
        'szz', help='Run SZZ on a directory with reproducers')
    szz_parser.add_argument('--reproducer_dir', required=True, default="reproducers.test",
                            help='Directory where reproducers shall be stored')

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()
    if args.command == "bisect":
        bisect.start(args)
    elif args.command == "bictrack":
        bictracker.start(args)
    elif args.command == "crawl":
        crawl.start(args)
    elif args.command == "szz":
        szz.start(args)
    elif args.command == "reproduce":
        testsingle.start(args)
    else:
        parser.print_help()


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s [%(levelname)-5.5s]  %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: format,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


if __name__ == "__main__":
    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.INFO)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(CustomFormatter())
    rootLogger.addHandler(consoleHandler)
    main()
