# Setup and daily use

This guide installs **Circuit Atlas**, the local web workbench. You do not need
Conda, a hosted LLM/API key, a GPU, a separate Java installation or AnalogGenie's
training environment. You do need a supported Python and a working Docker runtime.

## 1. Install prerequisites once

| Requirement | What to install/check |
| --- | --- |
| Python | **3.11–3.13**, preferably 3.13. Newer versions are not covered by this launcher yet. |
| Git | `git --version` should succeed. Needed for cloning and original dataset assets. |
| Docker | Docker Desktop on Mac, or Docker Desktop/Engine on Linux. `docker info` must succeed. |
| Internet and storage | Needed for initial Python packages, source assets, Neo4j image and pretrained text model. Allow several GB of free disk space. |

### macOS

1. Install Python 3.13 from [Python's official downloads](https://www.python.org/downloads/).
   If you already manage Python with another tool, use an existing supported version.
2. Run `git --version` in Terminal. If macOS offers to install command-line tools,
   follow that prompt; Git does not require the full Xcode application.
3. Install [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/),
   choosing the download for your Intel or Apple Silicon Mac. Open it and complete
   first-run prompts. Wait until its engine is running.

The project does not silently install system software. Do not run its setup with
`sudo`. Once Docker is installed, the Mac launcher can open Docker Desktop if stopped.

### Linux

Use your distribution's Git, Python and Python-venv packages, then install Docker
using its official instructions. On Ubuntu 24.04, Python 3.12 is suitable:

```bash
sudo apt-get update
sudo apt-get install git python3 python3-venv python3-pip
```

Docker: [Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/)
or [other distributions](https://docs.docker.com/engine/install/).
Configure Docker access so `docker info` works as your normal user. Docker-group
membership grants powerful host access; follow the official security guidance.
Do not solve a Docker permission error by running the whole workbench as root.

### Windows

There is no native Windows launcher in this V1. Use an Ubuntu **WSL2** environment
with Git/Python installed inside it and Docker Desktop's WSL integration enabled.
Follow the Linux commands from the WSL terminal, preferably cloning into its Linux
filesystem. Browser auto-open may not work there; open the printed URL manually.
This route has not been end-to-end verified on Windows.

## 2. Get the repository

### Recommended: clone with Git

```bash
git clone --recurse-submodules https://github.com/SatyagniCE/Topology-Querying.git
cd Topology-Querying
```

Cloning creates Git history and configures the `origin` remote automatically.
**Do not run `git init` after cloning.**

If cloned without submodules, setup fetches the missing AnalogGenie source assets.
You can also fetch them explicitly:

```bash
git submodule update --init --recursive
```

### Download ZIP instead

Download and extract the repository's ZIP. Open the extracted folder (its name may
end in `-main`). The canonical corpus is included, but GitHub's ZIP does not include
the submodule's original images/netlists. Setup uses Git to download those at the
pinned source revision. ZIP downloads are fine for using the app; co-developers
should clone instead. See [CONTRIBUTING.md](../CONTRIBUTING.md).

Do not run files from inside a ZIP preview. Extract them first.

## 3. Run setup once

### Mac: double-click

In Finder, open the project folder and double-click **Setup.command**. A Terminal
window shows progress. Wait for **Setup complete**, then press Return to close it.

If permission bits were lost during download, run this from Terminal in the folder:

```bash
chmod +x Setup.command Launch.command
```

If macOS blocks a downloaded command, inspect it and use the normal right-click
Open flow if permitted, or run the equivalent `bash` command below. Do not disable
system-wide security settings just to launch this project.

### All supported Unix environments: terminal

```bash
bash scripts/setup-workbench.sh
```

Setup checks prerequisites before installing project packages. It then:

1. Creates `.venv`, or reuses the existing valid project environment.
2. Installs dependencies into that environment, not system Python.
3. Fetches missing original AnalogGenie assets at the pinned revision.
4. Reuses `topology-querying-neo4j`, or creates it with the pinned
   `neo4j:2026.09.0` Community image and loopback-only ports.
5. Creates missing circuit graphs **without replacing existing circuits**.
6. Builds/reuses search indexes, syncs pending local records and waits for the
   two Neo4j vector indexes to come online.

Initial setup can take several minutes or longer depending on internet, disk and
CPU. It imports thousands of circuit graphs and prints progress. Subsequent
launches reuse the saved corpus/indexes; there is no repeated full import.

The first text index downloads BGE-small model weights (about 67 MB, plus cache
files). This is a pretrained text model, not circuit-model training. Source assets
are roughly 480 MB in the current checkout; Python and Docker/Neo4j add more.
Dependency versions use the ranges in `pyproject.toml`, not a fully locked environment.

**If interrupted:** rerun setup. Completed graph transactions and saved vectors
are reused. Do not delete the database or `output/` to start over.

Advanced options:

```bash
# Select a specific installed Python when no project environment exists:
TOPOLOGY_PYTHON=/absolute/path/to/python3.13 bash scripts/setup-workbench.sh

# Omit original source assets deliberately; images/reference text may be absent:
bash scripts/setup-workbench.sh --skip-sources

# Use a different web port if 8766 belongs to another application:
bash scripts/setup-workbench.sh --port 8767
```

Normal first-time setup should fetch sources. The catalog captures source text
when records first enter it; fetching assets later does not automatically rewrite
existing catalog records/reference text. Images are discovered from available files.

## 4. Launch on later days

**Mac:** double-click **Launch.command**.

**Terminal:**

```bash
bash scripts/run-workbench.sh
```

The launcher starts/reuses the project's Neo4j container, waits for connectivity,
starts the web app and opens your default browser after the app responds.
Default URL: [http://127.0.0.1:8766/](http://127.0.0.1:8766/).
If the same checkout is already running on that port, it opens that instance rather
than starting a second server. A different application/checkout on the port is refused.

Leave the terminal open. Stop the web app with **Ctrl+C**. Neo4j stays running so
restarting the app is quick. To stop just this project's database without deleting data:

```bash
docker stop topology-querying-neo4j
```

The next launch starts it again. With `--restart unless-stopped`, the container may
also resume when Docker restarts; stopping it explicitly suppresses that behavior.

Other launch options:

```bash
bash scripts/run-workbench.sh --port 8767
bash scripts/run-workbench.sh --no-open
bash scripts/run-workbench.sh --doctor
```

Use one checkout/catalog with the default database at a time. Two independent
checkouts need separate databases, not just different web ports.

## 5. Check the app is ready

Open Library, search `1004`, and inspect its graph/netlist/schematic. Check the
footer status for a ready index, Neo4j connectivity and zero pending synchronization.
A clean install contains 3,350 canonical circuits. Your local count grows with uploads.
There is no demo upload bundled as workbench state.

Try this in Query → Cypher:

```cypher
MATCH (c:Circuit)
RETURN count(c) AS circuits
```

If Neo4j later goes offline, the already running app can still show its local library
and NetworkX graphs. Live Neo4j graphs/Cypher are unavailable until the database
returns. The launcher itself requires connectivity to start a normal full session.

## Existing Neo4j installations and credentials

Docker is the default packaging choice so you do not need to manage Java and Neo4j
separately. It is not a requirement of graph retrieval itself.

New setups create a private password in `output/runtime/neo4j.env` with file mode
`0600`. Existing containers keep their existing password. Circuit Atlas reads the
project container's connection configuration locally; it does not ask you to log in
or display the password. Neo4j Browser at port 7474 has a separate database login.
Do not publish credentials or screenshots containing them.

If you already manage a **dedicated local** Neo4j database, the scripts can use it
without creating/starting a Docker container. Set these privately in your terminal:

```bash
export NEO4J_URI='bolt://127.0.0.1:7687'
export NEO4J_USER='neo4j'
export NEO4J_DATABASE='neo4j'
read -r -s -p 'Neo4j password: ' NEO4J_PASSWORD
export NEO4J_PASSWORD
printf '\n'
bash scripts/setup-workbench.sh
bash scripts/run-workbench.sh
```

This example uses Bash; run it in a Bash terminal rather than pasting the `read`
line into zsh unchanged. These environment variables are session-local. An ordinary
Finder launch will not inherit them; custom-database users should launch from that
configured terminal. Use a Neo4j version compatible with the repository's vector
queries; the default setup pins the version tested here.

Setup refuses a nonempty database with no matching catalog circuits. It does not
reset unrelated databases. It also refuses newer/conflicting database annotations
or database uploads absent from the local catalog: restore/reconcile the matching
catalog before continuing. The launch path checks this boundary too. A queued
newer local annotation can still sync normally; user data is not silently adopted
or cleared to resolve a mismatch.
Do not combine this Docker workflow with the legacy
private Linux Neo4j installer unless you intentionally configure separate ports.

## Backups and local data

| Location | Contains | Shared by Git? |
| --- | --- | --- |
| `data/analoggenie/` | Committed canonical source records | Yes |
| `AnalogGenie/` | Original upstream source assets | Submodule revision only |
| `output/workbench/` | SQLite catalog, uploads/images, annotations/history, vectors/model cache | No |
| `output/runtime/neo4j.env` | New setup's local database credential | No |
| Docker volume `topology-querying-neo4j-data` | Neo4j graphs and vector indexes | No |
| `.venv/` | Project Python packages | No; recreate on each machine |

Before backing up, stop the workbench cleanly. Copy the **whole**
`output/workbench/` directory, including any SQLite WAL/SHM files present, and retain
`output/runtime/neo4j.env` securely. Preserve the matching corpus/upstream revision.
Back up Neo4j's persistent data separately if you need an exact database restore;
follow [Neo4j's Docker volume guidance](https://neo4j.com/docs/operations-manual/current/docker/mounting-volumes/).

Restoring the SQLite/catalog state onto a compatible checkout and dedicated empty
database allows setup to recreate missing canonical and uploaded circuit graphs,
mark those records pending and sync their saved annotations/vectors. This is not
a general Neo4j backup utility; unrelated/manual database-only changes are not
represented in the local catalog. Never copy a live SQLite database casually.

Do **not** use `docker system prune`, remove the data volume, or delete `output/`
as routine cleanup. They can destroy or remove data the app needs.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| No supported Python found | Install 3.11–3.13; use `TOPOLOGY_PYTHON` if it is outside PATH. |
| `.venv` exists but is incomplete | Stop the app, rename only `.venv` to a backup name, rerun setup. Do not touch `output/`. |
| Docker missing/not ready | Open/install Docker; confirm `docker info` succeeds as your normal user. |
| Setup has not finished | Watch terminal progress; rerun after a failed download. Saved work is retained. |
| Port 8766 in use | Stop the old app or use `--port 8767` for both setup and launch. Old app versions without the new identity marker are treated as occupied ports. |
| Ports 7474/7687 in use | Configure your existing dedicated database explicitly; do not start a second one on the same ports. |
| Existing container is not loopback-only | Setup leaves it untouched. Correct its deployment manually while preserving its data, or use a dedicated configured local database. |
| Existing volume but missing credentials | Recover the matching credentials; a newly generated password cannot reset an existing Neo4j data volume. |
| Authentication fails after waiting | Check the original password/connection settings. Do not delete the volume to bypass the error. |
| Database annotations differ from the catalog | Restore the matching `output/workbench/` backup or deliberately reconcile the two states. Setup/launch stop before overwriting those annotations. |
| Circuit graph missing in Neo4j | Stop the app and rerun setup; it imports only missing catalog circuits. |
| Text model download fails | Check internet/disk; rerun setup. No hosted API key is needed. |
| No circuit image | Fetch source assets; some records have no corresponding image. Upload images are optional. |
| Finder opens a command as text | Use Terminal `bash scripts/setup-workbench.sh` / `bash scripts/run-workbench.sh`; confirm execute permission. |
| Moved the repository folder | Python virtual environments are not portable; recreate the environment at the new path while preserving local state. |

Read-only diagnosis:

```bash
bash scripts/run-workbench.sh --doctor
```

Doctor reports prerequisites, connectivity and vector-index availability. It does
not install anything, load a model, change database records or display credentials.
It is not an exhaustive per-record graph-integrity audit.

After pulling dependency/runtime changes, stop the app and rerun setup. See
[the co-developer guide](../CONTRIBUTING.md) before merging or pushing changes.

## Older tools

`scripts/setup-ubuntu.sh`, `scripts/run-local.sh` and `scripts/neo4j-local.sh`
are retained for the earlier Ubuntu/private-Neo4j/static-viewer workflow. They
are **not** the recommended Circuit Atlas setup. Static HTML under `visualizations/`
can be opened offline, but it does not include workbench uploads, edits or queries.

## Official references

- [Python virtual environments](https://docs.python.org/3/library/venv.html)
- [Neo4j Docker setup and persistence](https://neo4j.com/docs/operations-manual/current/docker/introduction/)
- [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/)
- [GitHub cloning guide](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository)
