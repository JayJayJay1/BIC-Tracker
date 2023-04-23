#!/usr/bin/env bash
# Runs bisection for a given list of reproducers with a given list of baseline configurations
#
# NOTE: Syz-bisect is using sudo. Before running this script ensure "sudo" is not asking for
# password. I.e. add "timestamp_timeout=-1" using "sudo visudo"

main() {
  export GO_VERSION=1.17.6
  BASE_DIR="/data/jakob.steeg-thesis/workspace"
  export GOROOT="$BASE_DIR/go"
  export PATH="$BASE_DIR/go/bin:${PATH}"
  export PATH="$BASE_DIR/syzkaller/bin:${PATH}"
  export PYTHONPATH="/data/jakob.steeg-thesis/implementation"

  echo "Starting single-test experiment"
  if [ -z "$REPRODUCER_DIR" ]; then
    echo "REPRODUCER_DIR not set"
    exit 1
  else
    echo "REPRODUCER_DIR is set to $REPRODUCER_DIR"
  fi
  # REPRODUCER_DIR="/data/jakob.steeg-thesis/workspace/reproducers/test_repros"
  if [ -z "$LINUX" ]; then
    echo "LINUX not set"
    exit 1
  else
    echo "LINUX is set to $LINUX"
  fi
  # LINUX="/data/jakob.steeg-thesis/workspace/linux"
  python3 -m autobisect.autobisect reproduce --reproducer_dir $REPRODUCER_DIR --retry_failed
  # --retry_failed --force --reproducer $REPRODUCER
  # --reproducer $REPRODUCER
}

main
