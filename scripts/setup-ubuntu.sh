#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    printf 'This setup supports Ubuntu 24.04 on x86_64 Linux.\n' >&2
    exit 2
fi
if [[ ! -f /etc/os-release ]]; then
    printf 'Cannot identify the operating system.\n' >&2
    exit 2
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
    printf 'This setup supports Ubuntu 24.04; found %s %s.\n' "${ID:-unknown}" "${VERSION_ID:-unknown}" >&2
    exit 2
fi
if ! command -v apt-get >/dev/null; then
    printf 'apt-get is required; use Ubuntu 24.04 for the one-command setup.\n' >&2
    exit 2
fi

if [[ "$(id -u)" == 0 ]]; then
    APT=(apt-get)
elif command -v sudo >/dev/null; then
    APT=(sudo apt-get)
else
    printf 'Run as root or install sudo to install system packages.\n' >&2
    exit 2
fi

"${APT[@]}" update
"${APT[@]}" install -y ca-certificates curl git openssl python3 python3-venv python3-pip tar

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[neo4j]'

if [[ ! -f "${HOME}/.config/query-retrieve/neo4j.env" ]]; then
    scripts/neo4j-local.sh install
elif ! scripts/neo4j-local.sh status >/dev/null 2>&1; then
    scripts/neo4j-local.sh start
fi

set -a
# shellcheck disable=SC1090
source "${HOME}/.config/query-retrieve/neo4j.env"
set +a

if ! .venv/bin/circuit-neo4j audit --report data/analoggenie/audit-report.json; then
    .venv/bin/circuit-neo4j import --input-dir data/analoggenie
    .venv/bin/circuit-neo4j audit --report data/analoggenie/audit-report.json
fi

if [[ ! -f output/networkx/manifest.json ]]; then
    .venv/bin/circuit-networkx build --input-dir data/analoggenie --output-dir output/networkx
fi
.venv/bin/circuit-networkx audit --output-dir output/networkx \
    --report data/analoggenie/audit-report.json

printf '\nSetup complete. Run ./scripts/run-local.sh to serve the visualizations.\n'
printf 'Neo4j Browser: http://127.0.0.1:7474\n'
printf 'Neo4j login is in %s/.config/query-retrieve/neo4j.env\n' "${HOME}"
