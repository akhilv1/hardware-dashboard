#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s tools -p 'test_*.py'
python3 -m unittest discover -s dashboard -p 'test_*.py'
python3 -m unittest discover -s dashboard/linux -p 'test_*.py'
python3 -m unittest discover -s dashboard/lxc -p 'test_*.py'
python3 -m unittest discover -s dashboard/updater -p 'test_*.py'
node dashboard/assets/resource-dials.test.cjs
node --test dashboard/assets/gpu-library/builder/fit.test.mjs
python3 tools/check_frontend.py
bash -n dashboard/lxc/build-lxc.sh dashboard/lxc/install-host-collector.sh
git diff --check
