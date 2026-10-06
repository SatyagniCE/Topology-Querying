#!/bin/bash
WORKBENCH_ROOT="$(cd "$(dirname "$0")" && pwd)"
bash "${WORKBENCH_ROOT}/scripts/setup-workbench.sh" "$@"
WORKBENCH_RESULT=$?
printf '\nPress Return to close this setup window.\n'
read -r
exit "${WORKBENCH_RESULT}"
