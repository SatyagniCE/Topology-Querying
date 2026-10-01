#!/usr/bin/env bash
set -euo pipefail

JRE_RELEASE='21.0.12.1_1'
NEO4J_RELEASE='2026.09.0'
JRE_ARCHIVE="OpenJDK21U-jre_x64_linux_hotspot_${JRE_RELEASE}.tar.gz"
NEO4J_ARCHIVE="neo4j-community-${NEO4J_RELEASE}-unix.tar.gz"
JRE_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/${JRE_ARCHIVE}"
NEO4J_URL="https://dist.neo4j.org/${NEO4J_ARCHIVE}"
INSTALL_ROOT="${HOME}/.local/opt"
JRE_HOME="${INSTALL_ROOT}/temurin-21"
NEO4J_HOME="${INSTALL_ROOT}/neo4j-community-${NEO4J_RELEASE}"
ENV_FILE="${HOME}/.config/query-retrieve/neo4j.env"

usage() {
    printf 'Usage: %s install|start|stop|status|console\n' "$0" >&2
    exit 2
}

neo4j_command() {
    if [[ ! -x "${JRE_HOME}/bin/java" || ! -x "${NEO4J_HOME}/bin/neo4j" ]]; then
        printf 'Neo4j runtime is not installed. Run %s install first.\n' "$0" >&2
        exit 1
    fi
    JAVA_HOME="${JRE_HOME}" PATH="${JRE_HOME}/bin:${PATH}" \
        "${NEO4J_HOME}/bin/neo4j" "$@"
}

download_and_check() {
    local url="$1"
    local archive="$2"
    local checksum_suffix="$3"
    local expected actual
    curl --fail --location --silent --show-error --retry 3 \
        --output "${archive}" "${url}"
    expected="$(curl --fail --location --silent --show-error --retry 3 "${url}${checksum_suffix}" | awk 'NR == 1 { print $1 }')"
    if [[ ! "${expected}" =~ ^[0-9a-fA-F]{64}$ ]]; then
        printf 'Invalid published SHA-256 for %s\n' "${url}" >&2
        exit 1
    fi
    actual="$(sha256sum "${archive}" | awk '{ print $1 }')"
    if [[ "${actual,,}" != "${expected,,}" ]]; then
        printf 'SHA-256 mismatch for %s\n' "${archive}" >&2
        exit 1
    fi
}

install_runtime() {
    if [[ -e "${JRE_HOME}" || -e "${NEO4J_HOME}" || -e "${ENV_FILE}" ]]; then
        printf 'A local runtime or credential file already exists; refusing to overwrite it.\n' >&2
        exit 1
    fi
    umask 077
    mkdir -p "${INSTALL_ROOT}" "$(dirname "${ENV_FILE}")"
    local jre_directory neo4j_directory password
    INSTALL_TEMPORARY="$(mktemp -d "${INSTALL_ROOT}/.neo4j-install.XXXXXXXX")"
    trap 'rm -rf -- "${INSTALL_TEMPORARY}"' EXIT

    download_and_check "${JRE_URL}" "${INSTALL_TEMPORARY}/${JRE_ARCHIVE}" '.sha256.txt'
    download_and_check "${NEO4J_URL}" "${INSTALL_TEMPORARY}/${NEO4J_ARCHIVE}" '.sha256'
    mkdir "${INSTALL_TEMPORARY}/jre" "${INSTALL_TEMPORARY}/neo4j"
    tar -xzf "${INSTALL_TEMPORARY}/${JRE_ARCHIVE}" -C "${INSTALL_TEMPORARY}/jre"
    tar -xzf "${INSTALL_TEMPORARY}/${NEO4J_ARCHIVE}" -C "${INSTALL_TEMPORARY}/neo4j"
    jre_directory="$(find "${INSTALL_TEMPORARY}/jre" -mindepth 1 -maxdepth 1 -type d -print -quit)"
    neo4j_directory="$(find "${INSTALL_TEMPORARY}/neo4j" -mindepth 1 -maxdepth 1 -type d -print -quit)"
    if [[ ! -x "${jre_directory}/bin/java" || ! -x "${neo4j_directory}/bin/neo4j" ]]; then
        printf 'Downloaded archives do not contain the expected executables.\n' >&2
        exit 1
    fi
    mv "${jre_directory}" "${JRE_HOME}"
    mv "${neo4j_directory}" "${NEO4J_HOME}"

    cat >> "${NEO4J_HOME}/conf/neo4j.conf" <<'CONFIG'
server.default_listen_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:7687
server.http.listen_address=127.0.0.1:7474
server.fleet_discovery.enabled=false
dbms.fleet_manager.enabled=false
dbms.usage_report.enabled=false
CONFIG

    password="$(openssl rand -hex 24)"
    JAVA_HOME="${JRE_HOME}" PATH="${JRE_HOME}/bin:${PATH}" \
        "${NEO4J_HOME}/bin/neo4j-admin" dbms set-initial-password "${password}" >/dev/null
    {
        printf 'NEO4J_URI=bolt://127.0.0.1:7687\n'
        printf 'NEO4J_USER=neo4j\n'
        printf 'NEO4J_PASSWORD=%s\n' "${password}"
        printf 'NEO4J_DATABASE=neo4j\n'
    } > "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    neo4j_command start
    rm -rf -- "${INSTALL_TEMPORARY}"
    trap - EXIT
    printf 'Local Neo4j installed. Credentials: %s (mode 0600)\n' "${ENV_FILE}"
    printf 'Bolt: bolt://127.0.0.1:7687; Browser: http://127.0.0.1:7474\n'
}

case "${1:-}" in
    install) install_runtime ;;
    start) neo4j_command start ;;
    stop) neo4j_command stop ;;
    status) neo4j_command status ;;
    console) neo4j_command console ;;
    *) usage ;;
esac
