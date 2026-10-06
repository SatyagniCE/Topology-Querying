#!/usr/bin/env bash
set -euo pipefail
WORKBENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKBENCH_ROOT}"
source "${WORKBENCH_ROOT}/scripts/workbench-env.sh"
export PYTHONPATH="${WORKBENCH_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

# Prefer the existing project environment; never replace a user's system Python.
WORKBENCH_PYTHON="${TOPOLOGY_PYTHON:-}"
if [[ -z "${WORKBENCH_PYTHON}" && -x .venv/bin/python ]]; then
    WORKBENCH_PYTHON="${WORKBENCH_ROOT}/.venv/bin/python"
fi
if [[ -z "${WORKBENCH_PYTHON}" ]]; then
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "${candidate}" >/dev/null 2>&1 && \
           "${candidate}" -c 'import sys; sys.exit(not ((3,11) <= sys.version_info[:2] <= (3,13)))' 2>/dev/null; then
            WORKBENCH_PYTHON="$(command -v "${candidate}")"
            break
        fi
    done
fi
if [[ -z "${WORKBENCH_PYTHON}" ]]; then
    printf 'Install Python 3.11–3.13 (3.13 recommended), then retry. See docs/setup.md.\n' >&2
    exit 1
fi
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    exec "${WORKBENCH_PYTHON}" -m circuit_workbench.local_runtime setup --help
fi
"${WORKBENCH_PYTHON}" -m circuit_workbench.local_runtime preflight --root "${WORKBENCH_ROOT}" "$@"
if [[ ! -x .venv/bin/python ]]; then
    if [[ -e .venv ]]; then
        printf '.venv exists but is incomplete. Leave it intact and see docs/setup.md.\n' >&2
        exit 1
    fi
    printf 'Creating a project-only Python environment…\n'
    "${WORKBENCH_PYTHON}" -m venv .venv
fi
printf 'Installing/checking workbench dependencies inside .venv…\n'
.venv/bin/python -m pip install -e '.[workbench]'
exec .venv/bin/python -m circuit_workbench.local_runtime setup --root "${WORKBENCH_ROOT}" "$@"
