#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! scripts/neo4j-local.sh status >/dev/null 2>&1; then
    scripts/neo4j-local.sh start
fi
printf 'Visualizations: http://127.0.0.1:8765/\n'
printf 'Neo4j Browser: http://127.0.0.1:7474/\n'
exec .venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory visualizations
