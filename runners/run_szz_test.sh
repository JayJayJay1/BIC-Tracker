#!/usr/bin/env bash
# Runs bictrack for a given list of reproducers
#
# This script must be run with sudo

main() {
  BASE_DIR="/data/jakob.steeg-thesis/workspace"
  export PYTHONPATH="/data/jakob.steeg-thesis/implementation"
  export TMPDIR="/data/jakob.steeg-thesis/tmp2"
  git config --global gc.auto 0
  echo "Starting szz experiment"
  if [ -z "$REPRODUCER_DIR" ]; then
    echo "REPRODUCER_DIR not set"
    exit 1
  else
    echo "REPRODUCER_DIR is set to $REPRODUCER_DIR"
  fi
  python3 -m autobisect.autobisect szz --reproducer_dir $REPRODUCER_DIR 
}

main