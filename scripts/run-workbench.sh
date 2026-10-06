#!/usr/bin/env bash
set -euo pipefail
WORKBENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKBENCH_ROOT}"
source "${WORKBENCH_ROOT}/scripts/workbench-env.sh"
if [[ ! -x .venv/bin/python ]]; then
    printf 'Run setup first: double-click Setup.command (Mac) or bash scripts/setup-workbench.sh\nSee docs/setup.md for prerequisites.\n' >&2
    exit 1
fi
# Explicit source path also works on macOS when the OS marks editable .pth
# files hidden: Python 3.13 ignores those files. No system Python modification.
export PYTHONPATH="${WORKBENCH_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
WORKBENCH_COMMAND=launch
if [[ "${1:-}" == --doctor ]]; then
    WORKBENCH_COMMAND=doctor
    shift
fi
exec .venv/bin/python -m circuit_workbench.local_runtime "${WORKBENCH_COMMAND}" --root "${WORKBENCH_ROOT}" "$@"
