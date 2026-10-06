"""Protect the newcomer launcher against data loss, leaks and port collisions."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import stat
import threading

import pytest


@contextmanager
def http_service(payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_launcher_recognizes_only_this_checkout(tmp_path):
    from circuit_workbench.local_runtime import running_workbench
    payload = {"application": "circuit-atlas", "project": str(tmp_path.resolve()),
               "circuits": 3, "retrieval": {}, "neo4j": {}}
    with http_service(payload) as port:
        assert running_workbench(tmp_path, port)["circuits"] == 3
        assert running_workbench(tmp_path / "another checkout", port) is None
    with http_service({"circuits": 3}) as port:
        assert running_workbench(tmp_path, port) is None


def test_launcher_refuses_an_unrelated_occupied_port(tmp_path):
    from circuit_workbench.local_runtime import launch, SetupError
    with http_service({"application": "another app"}) as port:
        with pytest.raises(SetupError, match="already in use"):
            launch(tmp_path, port, open_browser=False)


def test_launch_reuses_existing_ui_without_starting_database(tmp_path, monkeypatch):
    from circuit_workbench import local_runtime as runtime
    payload = {"application": "circuit-atlas", "project": str(tmp_path.resolve()),
               "circuits": 3, "retrieval": {}, "neo4j": {}}
    def unexpected(*args, **kwargs):
        pytest.fail("Launching an already running workbench must not alter the database")
    monkeypatch.setattr(runtime, "ensure_neo4j", unexpected)
    with http_service(payload) as port:
        assert runtime.launch(tmp_path, port, open_browser=False) == 0


def test_secret_file_is_private_and_never_overwritten(tmp_path):
    from circuit_workbench.local_runtime import credentials_file
    path = credentials_file(tmp_path)
    first = path.read_text()
    assert first.startswith("NEO4J_AUTH=neo4j/")
    assert len(first.strip().split("/", 1)[1]) >= 24
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert credentials_file(tmp_path).read_text() == first


def test_docker_create_is_persistent_loopback_only_and_does_not_expose_secret(tmp_path, monkeypatch, capsys):
    from circuit_workbench import local_runtime as runtime
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("inspect", runtime.CONTAINER):
            return None
        if args[:2] == ("volume", "inspect"):
            return None
        return "created-container"
    monkeypatch.setattr(runtime, "docker", docker)
    monkeypatch.setattr(runtime, "port_in_use", lambda port: False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    runtime.ensure_neo4j(tmp_path)
    create = next(args for args in calls if args[0] == "run")
    assert "127.0.0.1:7474:7474" in create
    assert "127.0.0.1:7687:7687" in create
    assert f"{runtime.VOLUME}:/data" in create
    assert "--env-file" in create
    secret = (tmp_path / "output/runtime/neo4j.env").read_text().split("/", 1)[1].strip()
    assert all(secret not in argument for args in calls for argument in args)
    assert secret not in capsys.readouterr().out


def test_existing_container_is_reused_without_recreating_credentials(tmp_path, monkeypatch):
    from circuit_workbench import local_runtime as runtime
    calls = []
    info = [{"State": {"Running": False}, "HostConfig": {"PortBindings": {
        "7474/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7474"}],
        "7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "7687"}],
    }}}]
    def docker(*args, **kwargs):
        calls.append(args)
        return json.dumps(info) if args[0] == "inspect" else "started"
    monkeypatch.setattr(runtime, "docker", docker)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    runtime.ensure_neo4j(tmp_path)
    assert calls == [("inspect", runtime.CONTAINER), ("start", runtime.CONTAINER)]
    assert not (tmp_path / "output/runtime/neo4j.env").exists()


def test_existing_volume_without_credentials_is_not_reset(tmp_path, monkeypatch):
    from circuit_workbench import local_runtime as runtime
    def docker(*args, **kwargs):
        if args[0] == "inspect":
            return None
        if args[:2] == ("volume", "inspect"):
            return '[{"Name":"existing-volume"}]'
        pytest.fail("Must not create a replacement container with a new password")
    monkeypatch.setattr(runtime, "docker", docker)
    monkeypatch.setattr(runtime, "port_in_use", lambda port: False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    with pytest.raises(runtime.SetupError, match="credentials"):
        runtime.ensure_neo4j(tmp_path)


def test_publicly_bound_existing_container_is_rejected(tmp_path, monkeypatch):
    from circuit_workbench import local_runtime as runtime
    info = [{"State": {"Running": True}, "HostConfig": {"PortBindings": {
        "7687/tcp": [{"HostIp": "0.0.0.0", "HostPort": "7687"}],
    }}}]
    monkeypatch.setattr(runtime, "docker", lambda *args, **kwargs: json.dumps(info))
    monkeypatch.delenv("NEO4J_URI", raising=False)
    with pytest.raises(runtime.SetupError, match="loopback"):
        runtime.ensure_neo4j(tmp_path)


def test_custom_connection_does_not_touch_docker(tmp_path, monkeypatch):
    from circuit_workbench import local_runtime as runtime
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:17687")
    monkeypatch.setenv("NEO4J_PASSWORD", "private-test-credential")
    monkeypatch.setattr(runtime, "docker", lambda *args, **kwargs: pytest.fail("Docker must not be called"))
    runtime.ensure_neo4j(tmp_path)


def test_custom_nonlocal_database_is_rejected(tmp_path, monkeypatch):
    from circuit_workbench import local_runtime as runtime
    monkeypatch.setenv("NEO4J_URI", "bolt://remote.example:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "private-test-credential")
    with pytest.raises(runtime.SetupError, match="local"):
        runtime.ensure_neo4j(tmp_path)


def test_setup_marks_recreated_graphs_for_resync_without_changing_user_data(tmp_path):
    from circuit_workbench.local_runtime import mark_imported_pending
    from circuit_workbench.catalog import Catalog
    db = Catalog(tmp_path / "state", tmp_path / "corpus", tmp_path / "upstream")
    with db.connect() as connection:
        connection.execute("INSERT INTO circuits(id,record,netlist,metadata,revision,modified,source_hash,sync_state) VALUES(?,?,?,?,?,?,?,?)",
                           ("example:1", "{}", "original netlist", '{"notes":"keep this"}', 7, "original date", "hash", "synced"))
    mark_imported_pending(db, ["example:1"])
    row = db.row("example:1")
    assert row["sync_state"] == "pending"
    assert row["metadata"] == '{"notes":"keep this"}'
    assert row["revision"] == 7
    assert row["netlist"] == "original netlist"


def test_status_exposes_checkout_identity_for_safe_launcher(tmp_path):
    from circuit_workbench.app import create_app
    from circuit_workbench.settings import Settings
    from fastapi.testclient import TestClient
    settings = Settings(tmp_path, tmp_path / "state", tmp_path / "corpus", tmp_path / "upstream")
    with TestClient(create_app(settings, background=False)) as client:
        status = client.get("/api/status").json()
    assert status["application"] == "circuit-atlas"
    assert status["project"] == str(tmp_path.resolve())


def test_doctor_distinguishes_occupied_port_from_stopped_app(tmp_path, monkeypatch, capsys):
    from circuit_workbench import local_runtime as runtime
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    with http_service({"application": "legacy or unrelated app"}) as port:
        runtime.doctor(tmp_path, port)
    assert "port occupied" in capsys.readouterr().out
