"""Local setup/launch tools. No system installs, database resets or cloud services."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import urlopen
import webbrowser

CONTAINER = "topology-querying-neo4j"
VOLUME = "topology-querying-neo4j-data"
IMAGE = "neo4j:2026.09.0"
UPSTREAM_URL = "https://github.com/xz-group/AnalogGenie.git"
UPSTREAM_COMMIT = "efc25358939c6bedd247f28d3df61066964f3a90"
ROOT = Path(__file__).resolve().parents[2]


class SetupError(RuntimeError):
    pass


def docker(*args, optional=False, timeout=180):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("Docker is unavailable or timed out. Start Docker and try again.") from exc
    if result.returncode:
        if optional:
            return None
        # Never echo inspect output, environment values or a command containing secrets.
        raise SetupError(f"Docker {args[0]} failed. Check Docker Desktop/Engine and free disk space.")
    return result.stdout.strip()


def custom_database():
    uri = os.environ.get("NEO4J_URI", "")
    if not uri:
        return False
    parsed = urlparse(uri)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
        raise SetupError("This launcher supports local Neo4j only; keep credentials out of the URI.")
    if not os.environ.get("NEO4J_PASSWORD"):
        raise SetupError("Set NEO4J_PASSWORD privately when using a custom NEO4J_URI.")
    return True


def ensure_docker_ready():
    if custom_database():
        return
    if not shutil.which("docker"):
        raise SetupError("Install Docker Desktop (Mac) or Docker Engine (Linux), then retry. See docs/setup.md.")
    if docker("info", optional=True, timeout=10) is not None:
        return
    if sys.platform != "darwin":
        raise SetupError("Start Docker Desktop/Engine, then retry; docker info must succeed.")
    print("Starting Docker Desktop; waiting up to 90 seconds…", flush=True)
    subprocess.run(["open", "-a", "Docker"], capture_output=True, check=False)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if docker("info", optional=True, timeout=10) is not None:
            return
        time.sleep(2)
    raise SetupError("Docker did not become ready. Open Docker Desktop, complete its first-run setup, then retry.")


def credentials_file(root):
    path = root / "output/runtime/neo4j.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        os.chmod(path, 0o600)
        return path
    with os.fdopen(fd, "w") as handle:
        handle.write("NEO4J_AUTH=neo4j/" + secrets.token_urlsafe(32) + "\n")
    return path


def port_in_use(port):
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def ensure_neo4j(root):
    if custom_database():
        print("Using the explicitly configured local Neo4j database.", flush=True)
        return
    info = docker("inspect", CONTAINER, optional=True)
    if info is not None:
        container = json.loads(info)[0]
        bindings = container["HostConfig"].get("PortBindings") or {}
        for port in ("7474", "7687"):
            entries = bindings.get(port + "/tcp", [])
            if not entries or any(item.get("HostIp") not in {"127.0.0.1", "::1"}
                                  or item.get("HostPort") != port for item in entries):
                raise SetupError("Existing Neo4j container is not bound to the expected loopback ports. "
                                 "Its data was left untouched; see docs/setup.md.")
        if not container["State"]["Running"]:
            docker("start", CONTAINER)
        print("Reusing the existing project Neo4j container.", flush=True)
        return
    for port in (7474, 7687):
        if port_in_use(port):
            raise SetupError(f"Port {port} is already in use. Configure your existing Neo4j explicitly; see docs/setup.md.")
    credentials = root / "output/runtime/neo4j.env"
    if docker("volume", "inspect", VOLUME, optional=True) is not None and not credentials.exists():
        raise SetupError("An existing Neo4j data volume has no matching credentials file. "
                         "Restore its credentials; setup will not reset the volume or password.")
    credentials = credentials_file(root)
    print("Creating the local Neo4j container (first run may download its image)…", flush=True)
    docker("run", "--detach", "--name", CONTAINER, "--restart", "unless-stopped",
           "--publish", "127.0.0.1:7474:7474", "--publish", "127.0.0.1:7687:7687",
           "--volume", f"{VOLUME}:/data", "--env-file", str(credentials),
           "--env", "NEO4J_server_memory_heap_initial__size=256m",
           "--env", "NEO4J_server_memory_heap_max__size=512m",
           "--env", "NEO4J_server_memory_pagecache_size=256m", IMAGE, timeout=600)


def running_workbench(root, port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as response:
            data = json.load(response)
        if data.get("application") == "circuit-atlas" and data.get("project") == str(root.resolve()):
            return data
    except (OSError, ValueError):
        pass
    return None


def preflight(root, port):
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        raise SetupError("Use Python 3.11–3.13 (3.13 recommended), not the macOS system Python. See docs/setup.md.")
    if not (root / "data/analoggenie/circuits/1004.json").is_file():
        raise SetupError("The canonical corpus is missing. Download/clone the complete repository.")
    if port_in_use(port):
        raise SetupError(f"Port {port} is already in use. Stop the workbench before setup or choose --port 8767.")
    ensure_docker_ready()


def fetch_sources(root):
    upstream = root / "AnalogGenie"
    if (upstream / "Dataset/1004/1004.cir").is_file():
        print("AnalogGenie source assets are already available; leaving them unchanged.", flush=True)
        return
    if not shutil.which("git"):
        raise SetupError("Install Git to fetch original schematics/netlists. See docs/setup.md.")
    print("Fetching original AnalogGenie assets at the pinned revision…", flush=True)
    if (root / ".git").exists():
        command = ["git", "submodule", "update", "--init", "--recursive", "AnalogGenie"]
        if subprocess.run(command, cwd=root).returncode:
            raise SetupError("Submodule download failed. Check internet access and any local AnalogGenie changes.")
    else:
        if upstream.exists() and any(upstream.iterdir()):
            raise SetupError("AnalogGenie is nonempty but incomplete; leave it intact and use a fresh clone.")
        command = ["git", "clone", "--no-checkout", UPSTREAM_URL, str(upstream)]
        if subprocess.run(command, cwd=root).returncode:
            raise SetupError("AnalogGenie download failed. Retry using git clone --recurse-submodules.")
        if subprocess.run(["git", "checkout", "--detach", UPSTREAM_COMMIT], cwd=upstream).returncode:
            raise SetupError("Could not select the pinned AnalogGenie revision.")
    if not (upstream / "Dataset/1004/1004.cir").is_file():
        raise SetupError("Original source assets are still missing after the download.")


def database_driver(settings, timeout=120):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password),
                                 connection_timeout=3, connection_acquisition_timeout=4)
    deadline = time.monotonic() + timeout
    print("Waiting for Neo4j connectivity…", flush=True)
    while True:
        try:
            driver.verify_connectivity()
            return driver
        except Exception:
            if time.monotonic() >= deadline:
                driver.close()
                raise SetupError("Neo4j is not ready or authentication failed. Data is unchanged. See docs/setup.md.") from None
            time.sleep(2)


def mark_imported_pending(catalog, identifiers):
    with catalog.connect() as db:
        db.executemany("UPDATE circuits SET sync_state='pending',sync_error='' WHERE id=?",
                       [(identifier,) for identifier in identifiers])


def annotation_rows(session):
    return list(session.run("""
        MATCH (c:Circuit)
        RETURN c.id AS id, c.metadata_revision AS revision,
               c{.title,.description,.family,.topology,.stage_count,
                 .input_mode,.output_mode,.tags,.notes} AS metadata
    """))


def guard_annotations(catalog, existing):
    """Never let a missing/stale local catalog silently erase database-side edits."""
    from .catalog import UserMetadata
    with catalog.connect() as db:
        local = {r["id"]: r for r in db.execute("SELECT id,metadata,revision FROM circuits")}
    for saved in existing:
        identifier = saved["id"]
        if identifier not in local:
            if str(identifier).startswith("uploaded:"):
                raise SetupError("Neo4j has uploads missing from this catalog. Restore the matching local catalog before setup/launch.")
            continue
        row = local[identifier]
        current = UserMetadata.model_validate_json(row["metadata"]).model_dump()
        try:
            remote = UserMetadata.model_validate({k: v for k, v in saved["metadata"].items() if v is not None}).model_dump()
        except ValueError:
            raise SetupError("Existing database annotations are incompatible. Restore/reconcile the matching catalog; nothing was overwritten.") from None
        revision = saved["revision"] or 0
        if revision > row["revision"] or (revision == row["revision"] and any(remote.values()) and remote != current):
            raise SetupError("Existing database annotations differ from or are newer than this local catalog. "
                             "Restore/reconcile the matching catalog before setup/launch; nothing was overwritten.")


def bootstrap(root, port, skip_sources=False):
    # Prevent two installers from importing/indexing this checkout simultaneously.
    import fcntl
    state = root / "output/runtime"
    state.mkdir(parents=True, exist_ok=True)
    with (state / "setup.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError("Setup is already running for this checkout.") from None
        if port_in_use(port):
            raise SetupError(f"Port {port} is already in use. Stop the workbench before setup.")
        if not skip_sources:
            fetch_sources(root)
        else:
            print("Skipping source assets: original images/reference text may be unavailable.", flush=True)
        ensure_neo4j(root)
        os.environ["CIRCUIT_ROOT"] = str(root)
        from .settings import Settings
        from .catalog import Catalog
        from .retrieval import Retrieval
        from .neo4j import Neo4jService
        from circuit_ingest.neo4j_store import create_constraints, create_circuit_if_missing
        settings = Settings.local()
        catalog = Catalog(settings.state, settings.corpus, settings.upstream)
        with database_driver(settings) as driver:
            with driver.session(database=settings.neo4j_database) as session:
                nodes = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
                saved = annotation_rows(session) if nodes else []
                existing = {r["id"] for r in saved}
            with catalog.connect() as db:
                identifiers = [r[0] for r in db.execute("SELECT id FROM circuits ORDER BY id")]
            if nodes and not existing.intersection(identifiers):
                raise SetupError("The database contains unrelated data. Use a dedicated empty Neo4j database; nothing was replaced.")
            guard_annotations(catalog, saved)
            create_constraints(driver, settings.neo4j_database)
            missing = [identifier for identifier in identifiers if identifier not in existing]
            print(f"Circuit graphs: {len(identifiers)-len(missing)} present, {len(missing)} missing.", flush=True)
            imported = []
            for identifier in missing:
                # Persist intent BEFORE the graph transaction. A crash after its
                # commit must still leave a retryable pending SQLite record.
                mark_imported_pending(catalog, [identifier])
                if create_circuit_if_missing(driver, settings.neo4j_database, catalog.record(identifier)):
                    imported.append(identifier)
                if len(imported) and len(imported) % 100 == 0:
                    print(f"Imported {len(imported)}/{len(missing)} missing circuits…", flush=True)
            print("Building/reusing local search indexes (first run downloads BGE-small)…", flush=True)
            retrieval = Retrieval(catalog)
            retrieval.build()
            neo = Neo4jService(settings, catalog)
            try:
                neo.sync()
                if neo.state.get("error"):
                    raise SetupError("Neo4j index/sync failed. Saved data was retained; check the footer after launching.")
                with catalog.connect() as db:
                    pending = db.execute("SELECT count(*) FROM circuits WHERE sync_state!='synced'").fetchone()[0]
                if pending:
                    raise SetupError(f"{pending} circuits still need synchronization. Retry setup; do not delete local state.")
                deadline = time.monotonic() + 120
                while True:
                    with driver.session(database=settings.neo4j_database) as session:
                        indexes = list(session.run("SHOW VECTOR INDEXES YIELD name,state RETURN name,state"))
                    ready = {r["name"] for r in indexes if r["state"] == "ONLINE"}
                    if {"circuit_topology_idx", "circuit_semantic_idx"} <= ready:
                        break
                    if time.monotonic() >= deadline:
                        raise SetupError("Vector indexes are still populating. Launch and check status before vector queries.")
                    time.sleep(1)
            finally:
                neo.driver.close()
        print(f"\nSetup complete: {len(identifiers)} circuits ready. Existing records were not replaced.\n"
              "Mac: double-click Launch.command. Terminal: bash scripts/run-workbench.sh", flush=True)
    return 0


def launch(root, port, open_browser=True):
    url = f"http://127.0.0.1:{port}/"
    if running_workbench(root, port):
        print(f"Circuit Atlas is already running: {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        return 0
    if port_in_use(port):
        raise SetupError(f"Port {port} is already in use by another process/checkout. Use --port 8767 or stop that process.")
    ensure_docker_ready()
    ensure_neo4j(root)
    os.environ["CIRCUIT_ROOT"] = str(root)
    from .settings import Settings
    from .catalog import Catalog
    settings = Settings.local()
    if not (settings.state / "catalog.sqlite3").is_file():
        raise SetupError("Run Setup.command or setup-workbench.sh first; the local catalog is missing.")
    with database_driver(settings) as driver:
        catalog = Catalog(settings.state, settings.corpus, settings.upstream)
        with driver.session(database=settings.neo4j_database) as session:
            guard_annotations(catalog, annotation_rows(session))
    print(f"Circuit Atlas: {url}\nLeave this terminal open. Ctrl+C stops the UI; saved data is retained.\n"
          "Neo4j stays running; stop it separately if desired (see docs/setup.md).", flush=True)
    if open_browser:
        def open_when_ready():
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if running_workbench(root, port):
                    webbrowser.open(url)
                    return
                time.sleep(0.5)
            print(f"Browser auto-open timed out; open {url} manually.", flush=True)
        threading.Thread(target=open_when_ready, daemon=True).start()
    from .cli import main as serve
    sys.argv = ["circuit-workbench", "--root", str(root), "--port", str(port)]
    serve()
    return 0


def doctor(root, port):
    checks = []
    def report(name, okay, hint=""):
        checks.append(okay)
        print(f"{'OK  ' if okay else 'FIX '} {name}" + (f" — {hint}" if not okay else ""))
    report("Python 3.11–3.13", (3, 11) <= sys.version_info[:2] <= (3, 13), "see docs/setup.md")
    report("Project environment", (root / ".venv/bin/python").is_file(), "run Setup.command or setup-workbench.sh")
    report("Canonical corpus", (root / "data/analoggenie/circuits/1004.json").is_file(), "download the complete repository")
    report("Source schematics/netlists", (root / "AnalogGenie/Dataset/1004/1004.cir").is_file(), "rerun setup without --skip-sources")
    dependencies = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "uvicorn", "neo4j", "fastembed"))
    report("Workbench dependencies", dependencies, "run setup-workbench.sh")
    try:
        external = custom_database()
        available = external or (shutil.which("docker") and docker("info", optional=True, timeout=10) is not None)
        report("Database runtime", bool(available), "start Docker Desktop/Engine")
    except SetupError:
        available = False
        report("Database runtime", False, "check private NEO4J_* settings")
    if dependencies and available:
        os.environ["CIRCUIT_ROOT"] = str(root)
        from .settings import Settings
        from neo4j import GraphDatabase
        settings = Settings.local()
        try:
            with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password), connection_timeout=3) as driver:
                driver.verify_connectivity()
                report("Neo4j connectivity", True)
                rows, _, _ = driver.execute_query("SHOW VECTOR INDEXES YIELD name,state RETURN name,state", database_=settings.neo4j_database)
                report("Both vector indexes online", {r["name"] for r in rows if r["state"] == "ONLINE"} >= {"circuit_topology_idx", "circuit_semantic_idx"}, "rerun setup / wait for indexing")
        except Exception:
            report("Neo4j connectivity/indexes", False, "run setup or check credentials; secrets are not displayed")
    current = running_workbench(root, port)
    state = "running" if current else "port occupied by another/older app" if port_in_use(port) else "not running"
    print(f"INFO Workbench {state} at http://127.0.0.1:{port}/")
    print("No installs, resets or data changes were performed.")
    return 0 if all(checks) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up, launch or diagnose the local Circuit Atlas workbench.")
    parser.add_argument("command", choices=("preflight", "setup", "launch", "doctor"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-open", action="store_true", help="do not automatically open a browser")
    parser.add_argument("--skip-sources", action="store_true", help="omit original AnalogGenie source download (images may be missing)")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    root = args.root.resolve()
    try:
        if args.command == "preflight":
            preflight(root, args.port)
            return 0
        if args.command == "setup":
            preflight(root, args.port)
            return bootstrap(root, args.port, args.skip_sources)
        if args.command == "doctor":
            return doctor(root, args.port)
        return launch(root, args.port, not args.no_open)
    except SetupError as exc:
        print(f"\n{exc}\nHelp: docs/setup.md (Troubleshooting).", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Existing data was retained.")
        return 130
    except Exception as exc:
        print(f"\nOperation failed ({type(exc).__name__}). Existing data was retained. "
              "Retry setup or see docs/setup.md; no credentials are displayed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
