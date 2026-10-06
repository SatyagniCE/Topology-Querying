from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess


@dataclass
class Settings:
    root: Path
    state: Path
    corpus: Path
    upstream: Path
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    @classmethod
    def local(cls):
        root = Path(os.getenv("CIRCUIT_ROOT", Path.cwd())).resolve()
        password = os.getenv("NEO4J_PASSWORD", "")
        user = os.getenv("NEO4J_USER", "neo4j")
        # Reuse this project's existing local Docker runtime; never print secrets.
        if not password and shutil.which("docker"):
            try:
                info = json.loads(subprocess.check_output(
                    ["docker", "inspect", "topology-querying-neo4j"], timeout=4,
                    stderr=subprocess.DEVNULL))
                for item in info[0]["Config"].get("Env", []):
                    if item.startswith("NEO4J_AUTH=") and "/" in item:
                        user, password = item.split("=", 1)[1].split("/", 1)
            except (OSError, ValueError, subprocess.SubprocessError, KeyError):
                pass
        return cls(root, Path(os.getenv("CIRCUIT_STATE", root / "output/workbench")),
                   root / "data/analoggenie", root / "AnalogGenie",
                   os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"), user, password,
                   os.getenv("NEO4J_DATABASE", "neo4j"))
