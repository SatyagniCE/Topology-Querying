"""Opt-in fresh-database setup/launch check; never touches the user's database."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture
def fresh_setup(tmp_path, monkeypatch):
    if os.environ.get("NEO4J_SETUP_TEST") != "1":
        pytest.skip("Set NEO4J_SETUP_TEST=1 for the isolated Docker setup smoke")
    if not shutil.which("docker"):
        pytest.fail("Docker is required for NEO4J_SETUP_TEST")
    from circuit_workbench.local_runtime import credentials_file
    project = tmp_path / "fresh checkout with spaces"
    circuits = project / "data/analoggenie/circuits"
    circuits.mkdir(parents=True)
    for name in ("1004", "1009", "2030"):
        shutil.copyfile(ROOT / "data/analoggenie/circuits" / f"{name}.json", circuits / f"{name}.json")
    (project / "AnalogGenie").symlink_to(ROOT / "AnalogGenie", target_is_directory=True)
    (project / "src").symlink_to(ROOT / "src", target_is_directory=True)
    (project / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
    (project / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/run-workbench.sh", project / "scripts/run-workbench.sh")
    shutil.copy(ROOT / "scripts/workbench-env.sh", project / "scripts/workbench-env.sh")
    shutil.copy(ROOT / "Launch.command", project / "Launch.command")
    model = project / "output/workbench/model"
    model.parent.mkdir(parents=True)
    if (ROOT / "output/workbench/model").is_dir():
        model.symlink_to(ROOT / "output/workbench/model", target_is_directory=True)
    credentials = credentials_file(project)
    password = credentials.read_text().strip().split("/", 1)[1]
    port = unused_port()
    container = "topology-querying-setup-test-" + uuid4().hex[:12]
    # Use the user's already cached official image if available; no second image download.
    image = subprocess.run(["docker", "inspect", "--format", "{{.Config.Image}}", "topology-querying-neo4j"],
                           capture_output=True, text=True)
    tag = image.stdout.strip() if image.returncode == 0 else "neo4j:2026.09.0"
    command = ["docker", "run", "--rm", "--detach", "--name", container,
               "--label", "topology-querying.test=setup", "--publish", f"127.0.0.1:{port}:7687",
               "--tmpfs", "/data", "--tmpfs", "/logs", "--env-file", str(credentials),
               "--env", "NEO4J_server_memory_heap_initial__size=128m",
               "--env", "NEO4J_server_memory_heap_max__size=256m",
               "--env", "NEO4J_server_memory_pagecache_size=128m", tag]
    started = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if started.returncode:
        pytest.fail("Could not start the isolated temporary Neo4j container")
    monkeypatch.setenv("NEO4J_URI", f"bolt://127.0.0.1:{port}")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", password)
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.delenv("CIRCUIT_STATE", raising=False)
    try:
        yield project
    finally:
        # Exact test-owned container, tmpfs only, --rm cleans it and no production volume is mounted.
        subprocess.run(["docker", "stop", "--time", "5", container], capture_output=True, timeout=30)


def test_fresh_setup_resume_restore_and_click_launcher(fresh_setup):
    from circuit_workbench.local_runtime import bootstrap, running_workbench
    from circuit_workbench.catalog import Catalog
    from circuit_workbench.settings import Settings
    from neo4j import GraphDatabase
    project = fresh_setup
    port = unused_port()
    assert bootstrap(project, port) == 0
    settings = Settings.local()
    catalog = Catalog(settings.state, settings.corpus, settings.upstream)
    with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as driver:
        records, _, _ = driver.execute_query("MATCH (c:Circuit) RETURN count(c) AS n", database_="neo4j")
        assert records[0]["n"] == 3
        saved = catalog.edit("analoggenie:1004", {"notes": "Preserve this researcher note"}, revision=0)
        assert bootstrap(project, port) == 0
        assert catalog.row("analoggenie:1004")["revision"] == saved["revision"]
        records, _, _ = driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) RETURN c.notes AS notes", database_="neo4j")
        assert records[0]["notes"] == "Preserve this researcher note"
        # Simulate loss of this one test graph, keeping the local catalog/annotations.
        driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n) DETACH DELETE n", database_="neo4j")
        driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) DETACH DELETE c", database_="neo4j")
        assert bootstrap(project, port) == 0
        records, _, _ = driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) RETURN c.notes AS notes", database_="neo4j")
        assert records[0]["notes"] == "Preserve this researcher note"
    process = subprocess.Popen([str(project / "Launch.command"), "--port", str(port), "--no-open"],
                               cwd=project.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        status = None
        while time.monotonic() < deadline and process.poll() is None:
            status = running_workbench(project, port)
            if status:
                break
            time.sleep(0.25)
        assert status and status["circuits"] == 3
        # Clicking again reuses this checkout's existing instance rather than launching a duplicate.
        repeated = subprocess.run([str(project / "Launch.command"), "--port", str(port), "--no-open"],
                                  cwd=project.parent, capture_output=True, text=True, timeout=15)
        assert repeated.returncode == 0
        assert "already running" in repeated.stdout
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=10)


def test_setup_rejects_empty_local_annotations_over_existing_database_notes(fresh_setup, monkeypatch):
    from circuit_workbench.local_runtime import bootstrap, SetupError
    from circuit_workbench.settings import Settings
    from neo4j import GraphDatabase
    project = fresh_setup
    port = unused_port()
    assert bootstrap(project, port) == 0
    settings = Settings.local()
    with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as driver:
        driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) SET c.notes='Keep existing database note'", database_="neo4j")
        new_state = project / "output/fresh-catalog"
        new_state.mkdir()
        if (project / "output/workbench/model").exists():
            (new_state / "model").symlink_to(project / "output/workbench/model", target_is_directory=True)
        monkeypatch.setenv("CIRCUIT_STATE", str(new_state))
        with pytest.raises(SetupError, match="annotations"):
            bootstrap(project, port)
        records, _, _ = driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) RETURN c.notes AS notes", database_="neo4j")
        assert records[0]["notes"] == "Keep existing database note"


def test_interrupted_restore_keeps_pending_state_for_retry(fresh_setup, monkeypatch):
    from circuit_workbench.local_runtime import bootstrap
    from circuit_workbench.settings import Settings
    from circuit_workbench.catalog import Catalog
    from circuit_ingest import neo4j_store
    from neo4j import GraphDatabase
    project = fresh_setup
    port = unused_port()
    assert bootstrap(project, port) == 0
    settings = Settings.local()
    catalog = Catalog(settings.state, settings.corpus, settings.upstream)
    catalog.edit("analoggenie:1004", {"notes": "Restore this note after interruption"}, revision=0)
    assert bootstrap(project, port) == 0
    with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as driver:
        driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'})-[:HAS_DEVICE|HAS_NET|HAS_PORT]->(n) DETACH DELETE n", database_="neo4j")
        driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) DETACH DELETE c", database_="neo4j")
        original = neo4j_store.create_circuit_if_missing
        def interrupted(*args):
            original(*args)
            raise RuntimeError("Simulated interruption after graph commit")
        monkeypatch.setattr(neo4j_store, "create_circuit_if_missing", interrupted)
        with pytest.raises(RuntimeError, match="Simulated interruption"):
            bootstrap(project, port)
        assert catalog.row("analoggenie:1004")["sync_state"] == "pending"
        monkeypatch.setattr(neo4j_store, "create_circuit_if_missing", original)
        assert bootstrap(project, port) == 0
        records, _, _ = driver.execute_query("MATCH (c:Circuit {id:'analoggenie:1004'}) RETURN c.notes AS notes, size(c.topology_embedding) AS dimensions", database_="neo4j")
        assert dict(records[0]) == {"notes": "Restore this note after interruption", "dimensions": 768}
