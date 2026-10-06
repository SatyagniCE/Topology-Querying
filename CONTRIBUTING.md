# Co-developer guide

Use a Git clone for development, not Download ZIP. Each developer runs their own
local database/catalog. Code is shared through Git; local uploads, annotations,
credentials, model caches and database volumes are not.

## 1. Get access and clone

Ask the repository owner for collaborator access if you will push directly. You
can read/clone a public repository without that access; pushing needs GitHub
authentication and permission.

```bash
git clone --recurse-submodules https://github.com/SatyagniCE/Topology-Querying.git
cd Topology-Querying
git status
git remote -v
bash scripts/setup-workbench.sh
```

`git clone` already initializes Git history and sets `origin`. **Do not run
`git init` or create another initial commit in this cloned repository.**

Configure your commit identity once if it is not already configured:

```bash
git config --global user.name "Your Name"
git config --global user.email "your-github-email@example.com"
```

Use your actual identity. Remove `--global` if you only want to configure this repo.
For authentication, use GitHub's supported HTTPS credential manager/GitHub CLI
login or SSH keys. GitHub account passwords are not Git HTTPS push credentials.
Never put a personal-access token in a repository URL, source file or README.

## 2. Create a branch for your change

Start with a clean or deliberately saved working tree:

```bash
git status
git switch main
git pull --ff-only origin main
git submodule update --init --recursive
git switch -c codex/your-short-change-name
```

If you have uncommitted work, save it on its own branch first; do not force-switch,
reset or erase it. Branch names should describe the change. Avoid pushing directly
to `main` unless the team explicitly chooses that workflow.

## 3. Run and test

```bash
bash scripts/run-workbench.sh
```

Use a second terminal for tests, from the repository root:

```bash
.venv/bin/python -m pip install -e '.[workbench,test]'
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Neo4j integration tests are environment-gated. To require them, set private
`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` connection variables
and run:

```bash
NEO4J_TEST_REQUIRED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/integration -q
```

Integration tests create and clean up their own test circuits. Full-corpus audit
tests are a separate opt-in (`NEO4J_CORPUS_TEST=1`) and assume the expected canonical
corpus, without extra upload records affecting totals. Do not call skips a passing
integration check.

With the UI running and indexing/sync complete:

```bash
PYTHONPATH=src .venv/bin/python scripts/verify-workbench.py
```

That smoke check reads corpus content and writes successful-query history; it
does not annotate/upload circuits. Node is optional for UI helper tests:

```bash
node --test tests/ui/viewer-controls.test.mjs
```

For a running-status diagnosis that does not change data:

```bash
bash scripts/run-workbench.sh --doctor
```

## 4. Commit and push your branch

Review what changed and stage only your intended files:

```bash
git status --short
git diff
# Example; replace these with the actual files you changed:
git add README.md docs/setup.md
git diff --cached
git commit -m "docs: clarify local setup"
git push -u origin codex/your-short-change-name
```

Then open a GitHub pull request from your branch into `main`. Explain the change,
how to test it and any known limitations. The `-u` connects the local branch to
its remote branch; later pushes on it can use `git push`.

Before staging, inspect untracked files too: `git diff` does not display them.
The repository ignores `.venv/`, `output/`, `.env`/`.env.*`, logs and OS clutter.
Never force-add secrets, SQLite state, model downloads or Docker data.
User annotations are not shared by committing code; export/share them separately
only when that is deliberately required and reviewed.

## 5. Pull teammates' updates

For an unchanged local `main`:

```bash
git switch main
git pull --ff-only origin main
git submodule update --init --recursive
```

To bring the updated main branch into your existing feature branch:

```bash
git switch codex/your-short-change-name
git merge main
```

If Git reports conflicts, resolve the indicated files, test, stage the resolutions
and finish the merge with `git commit`. Do not use force-push or `reset --hard` as a
shortcut. `--ff-only` intentionally stops when histories diverge; ask/review before
choosing a merge or rebase.

After dependency/parser/runtime/index changes, stop the web app, rerun
`bash scripts/setup-workbench.sh`, then launch again. Setup does not refresh
already-present canonical graph topology from changed source JSON; an intentional
source-data migration needs its own reviewed procedure, not a blanket re-import.
Descriptor-version changes are rebuilt/synchronized by the workbench.

Do not update AnalogGenie casually with `git submodule update --remote`. The parent
repository pins a known revision; changing it is a separate data/parser change.

## Without write access: fork workflow

Fork the repository in GitHub, then clone **your fork**. Replace `YOUR_USERNAME`
below before running the command:

```bash
git clone --recurse-submodules https://github.com/YOUR_USERNAME/Topology-Querying.git
cd Topology-Querying
git remote add upstream https://github.com/SatyagniCE/Topology-Querying.git
git switch -c codex/your-short-change-name
```

Push the feature branch to your fork (`origin`) and open a pull request targeting
the original repository. To incorporate original-project updates, fetch upstream,
review/merge `upstream/main`, and update submodules.

## When is `git init` appropriate?

**Not for working on this existing GitHub project.** If you downloaded a ZIP and
now want to contribute, clone the repository properly and copy only your edited
source/docs into that clone. Do not copy `.git`, `.venv` or local `output/` state.
This preserves the actual project's history and avoids unrelated-history errors.

`git init` is for a genuinely new project and a **new, empty GitHub repository**.
For that separate situation, after reviewing `.gitignore` and all files:

```bash
git init -b main
git add .
git diff --cached --stat
git diff --cached
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_NEW_EMPTY_REPO.git
git push -u origin main
```

Replace the placeholder URL. Do not point this newly initialized history at the
existing `SatyagniCE/Topology-Querying` remote or force-push over its history.
Do not create a README/license commit on GitHub first if you intend to follow the
empty-repository example unchanged.

## Change boundaries

- Preserve device terminals, net ownership and circuit provenance.
- Do not turn structural candidates into asserted family/stage/spec labels.
- Keep read-only query guards, timeouts and loopback deployment intact.
- Add behavioral tests for parser/retrieval/runtime changes.
- Update setup/capability documentation when behavior changes.
- Add explicit migrations for canonical schema/data changes; preserve local user state.
- Do not claim 10k-scale accuracy or electrical correctness from a small regression suite.

References: [GitHub cloning](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository),
[pushing commits](https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository),
[authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github).
