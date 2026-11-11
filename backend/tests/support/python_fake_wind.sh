#!/usr/bin/env bash
# Stand-in for SFT_MODEL_PYTHON in tests: runs the real worker with the synthetic wind adapter.
exec "${PYTHON:-python3}" "$(dirname "$0")/run_worker.py" "$@"
