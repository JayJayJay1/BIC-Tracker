#!/usr/bin/env bash
# Runs bictrack for a given list of reproducers
#
# This script must be run with sudo

main() {
  export GO_VERSION=1.17.6
  BASE_DIR="/data/jakob.steeg-thesis/workspace"
  export GOROOT="$BASE_DIR/go"
  export GOCACHE="/data/jakob.steeg-thesis/tmp"
  export PATH="$BASE_DIR/go/bin:${PATH}"
  export PATH="$BASE_DIR/syzkaller/bin:${PATH}"
  export PYTHONPATH="/data/jakob.steeg-thesis/implementation"
  export TMPDIR="/data/jakob.steeg-thesis/tmp2"
  git config --global gc.auto 0
  echo "Starting bictracker experiment"
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
  # REPRODUCER="8e2620ee4ac7306654859489a322c33c4de99b20"
  # REPRODUCER=264b703d22effb171549375ad8aa17704033f1ae
  git -C $LINUX status
  python3 -m autobisect.autobisect bictrack --reproducer_dir $REPRODUCER_DIR --cache --linux $LINUX --retry_failed
  # --retest_skipped --reproducer $REPRODUCER --retry_failed --force --retest_skipped
}

main