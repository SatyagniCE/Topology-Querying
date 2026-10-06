#!/usr/bin/env bash
# Finder/Terminal launches may not inherit the developer's interactive PATH.
# Change only these launcher processes, never shell profiles or system settings.
if [[ "$(uname -s)" == Darwin ]]; then
    for WORKBENCH_BIN in /usr/local/bin /opt/homebrew/bin "${HOME}/.docker/bin"; do
        if [[ -d "${WORKBENCH_BIN}" ]]; then
            export PATH="${WORKBENCH_BIN}:${PATH}"
        fi
    done
fi
