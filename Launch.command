#!/bin/bash
WORKBENCH_ROOT="$(cd "$(dirname "$0")" && pwd)"
bash "${WORKBENCH_ROOT}/scripts/run-workbench.sh" "$@"
WORKBENCH_RESULT=$?
if [[ "${WORKBENCH_RESULT}" != 0 && "${WORKBENCH_RESULT}" != 130 ]]; then
    printf '\nLaunch could not finish. See docs/setup.md. Press Return to close.\n'
    read -r
fi
exit "${WORKBENCH_RESULT}"
