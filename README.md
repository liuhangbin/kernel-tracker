# kernel-tracker

[![CI](https://github.com/liuhangbin/kernel-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/liuhangbin/kernel-tracker/actions/workflows/ci.yml)

Track git trees, detect missing fixes, and monitor patch series.

Built on uv, Django 5.x and MariaDB, and **not limited to the Linux kernel** —
it works against any git repository. Tags become "versions",
`Fixes:` trailers become fix links, and commits are grouped into series by
author and time proximity.

## Contents

- [Requirements](#requirements)
- [Local development setup](#local-development-setup)
- [Adding a tree and fetching commits](#adding-a-tree-and-fetching-commits)
- [Configuration](#configuration)
- [Container setup](#container-setup)
- [Management commands](#management-commands)
- [Web UI and RPC API](#web-ui-and-rpc-api)
- [Development tasks](#development-tasks)
- [Current limitations](#current-limitations)

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.14+ | `requires-python = ">=3.14"`; uv installs it if missing |
| [uv](https://docs.astral.sh/uv/) | dependency and environment management |
| git | used to fetch trees |
| podman-compose (optional) | only for the container setup |
| MariaDB (optional) | only for the container setup; local dev uses SQLite |

## Local development setup

```bash
git clone <your-fork-url> kernel-tracker
cd kernel-tracker

# Install the project plus dev tools (pytest, ruff, black)
uv sync

# Create the database. With no configuration this is SQLite at src/db.sqlite3.
uv run manage migrate

# Optional: admin login at http://localhost:8000/admin/. Without an account
# nothing can be changed through the web UI.
uv run manage ensure_admin         # prints a generated password
# uv run manage createsuperuser    # or pick the name and password yourself

# Start the web UI
uv run manage runserver
```

Then open <http://localhost:8000/>. With no trees configured the page shows
setup instructions; once a tree is added you get the commit list.

`manage` is the console script defined in `pyproject.toml`. You can also run
`uv run python src/kernel_tracker/manage.py <command>` if you prefer.

## Adding a tree and fetching commits

```bash
# The FIRST tree added must be the vanilla (reference) tree.
# Format: tree add -u|-d [-V] <name> <url>[#branch]
uv run manage tree add -u -V upstream https://github.com/example/project.git

# Any further tree is added without -V
uv run manage tree add -d downstream https://github.com/example/fork.git#release

# Fetch new commits and run the processing pipeline
uv run manage cron update

# List configured trees
uv run manage tree show
```

`tree add` does **not** clone anything. It only saves the tree to the database
and creates a git remote inside `src/data.git`. The fetching happens in
`cron update`, which runs `git --git-dir src/data.git fetch <tree>` — so one
shared bare repo holds the objects of every tracked tree, one remote each,
rather than a clone per tree.

### What `-u`, `-d` and `-V` mean

| Flag | Meaning |
|---|---|
| `-u` / `--upstream` | an upstream tree — where the code originates |
| `-d` / `--downstream` | a downstream tree — receives backports from upstream |
| `-V` / `--vanilla` | this tree is *the* vanilla tree: the single reference mainline every other tree is compared against |

Rules:

- Specify exactly one of `-u` / `-d`.
- `-V` implies upstream and only **one** tree may have it. It should be the
  project's real mainline.
- The **first** tree you add must be `-V`.
- Any number of upstream trees can coexist under different names — e.g.
  `iproute2` (`-u -V`) and `iproute2-next` (`-u`) are both valid.
- Names are arbitrary and unrelated to the flags; nothing is forced to be
  called "upstream".
- The kind is fixed at add time. `tree change` updates only the URL and name,
  so changing `-u` to `-d` means deleting and re-adding the tree.

### Local git directories

Both forms work, and neither requires a network:

```bash
uv run manage tree add -u -V local /home/me/src/myproject
uv run manage tree add -u -V local file:///home/me/src/myproject
```

### Deleting a tree

```bash
uv run manage tree delete iproute2-next    # aliases: rm, remove
```

This removes the database row **and** the git remote. Commits themselves are
kept. You must retype the tree name to confirm. The vanilla tree cannot be
deleted while any other tree still exists, because the others are compared
against it.

Things to know:

- Only **one** tree can be vanilla, and it must be an upstream (`-u`) tree. It
  is the baseline that other trees are compared against.
- The branch defaults to `main`. Append `#<branch>` to the URL to track
  something else.
- `cron update` is what actually walks commits and records fixes, series, files
  and tags. Run it whenever you want to pick up new commits; keeping it on a
  schedule is either an entry in your crontab or, inside the container, the
  schedule described in [Scheduled updates](#scheduled-updates).
- A file lock (`_processing.lock` by default) prevents two runs at once.

## Scheduled updates

`cron daemon` updates every tree whenever the schedule says so, which means
the container can keep itself current without anything outside it:

```bash
uv run manage cron daemon      # stay on the schedule
uv run manage cron daemon --once
```

Nothing happens until the schedule is enabled in the admin: **Update
schedule** has one row, with the *enable scheduled updates* box (off by
default), the cron expression (`0 * * * *`, every hour) and the time of the
last update. Changes apply to the running daemon within a minute, there is
nothing to restart.

The expression is read in the configured timezone — see `TZ` below — so
`0 3 * * *` means three in the morning there, not in UTC. `cron update` and
the update action on the tree list are unaffected and still run on demand; the
file lock keeps them from overlapping a scheduled run.

## Configuration

Settings come from `src/kernel_tracker/settings_local.py`, falling back to
`src/kernel_tracker/settings_example.py` if that file does not exist. The
example defaults are enough for local development, so **no configuration is
needed to start**. To customize:

```bash
cp src/kernel_tracker/settings_example.py src/kernel_tracker/settings_local.py
```

`settings_local.py` is gitignored. Useful options:

| Setting | Meaning |
|---|---|
| `SECRET_KEY` | Django secret — **change before deploying** |
| `DEBUG` | dev vs production behaviour |
| `DBLITE` | path to a SQLite database (dev) |
| `DBNAME`/`DBUSER`/`DBPASSWD`/`DBHOST`/`DBPORT` | MariaDB; setting these switches off SQLite |
| `GIT_REPO` | bare repo the tracker fetches into (default `src/data.git`) |
| `PROCESSING_LOCK_FILE` | lock file used by `cron update` |
| `STATIC_DIR` | `collectstatic` target |
| `TIME_ZONE` | zone for displayed timestamps and the update schedule (default `UTC`) |

## Container setup

Runs gunicorn behind nginx with MariaDB.

```bash
cp compose_example.yaml compose.yaml   # local settings, git-ignored; edit freely
make start             # pull the image and start, waits for http://localhost:8080/health
make integration-test  # start, run tests/run inside the container, tear down
make debug             # start and run the integration tests, leaving it up
make attach            # shell inside the running container
make log               # show the container error log
make stop              # tear down
```

`.github/workflows/ci.yml` builds the image on every push and publishes it to
`ghcr.io/liuhangbin/kernel-tracker`: `latest` on the default branch, the
version for every `v*` tag, and a `sha-<short>` tag on every build. Pull
requests build without pushing. The compose file runs that published image:

```yaml
    image: ghcr.io/liuhangbin/kernel-tracker:latest
```

and it is fetched on first start, or refreshed with:

```bash
podman pull ghcr.io/liuhangbin/kernel-tracker:latest
```

Replace it with a `build: {dockerfile: Containerfile}` block to run your own
build of the source tree. Building needs the base image from `docker.io`, so
it does not work where that registry is blocked. The version shown in the
footer comes from the `KERNEL_TRACKER_VERSION` build argument:

```bash
podman build --build-arg KERNEL_TRACKER_VERSION=$(git describe --tags) \
    -t kernel-tracker .
```

The compose file maps `8080` (nginx) and `8443`. Database credentials are read
from the `MARIADB_*` environment variables in `compose_example.yaml`. Remove
those variables (and the `mariadb` service with its `depends_on`) and the
container falls back to SQLite.

The container runs nginx (in the foreground) with gunicorn behind it, and
`cron daemon` next to them, so it keeps its own trees up to date once that is
enabled in the admin; see [Scheduled updates](#scheduled-updates). Its output
goes to `./data/log/update.log`.

The state lives in host directories, bind mounted into the containers:

| Host | Container | Holds |
|---|---|---|
| `./data` | `/data` | the bare repository `data.git`, `db.sqlite3` when MariaDB is not configured, static files, and logs in `log/` |
| `./data/mysql` | `/var/lib/mysql` | MariaDB data directory |
| `${LOCAL_GIT_DIR:-./repos}` | `/git` | git trees to track, read-only |

Everything except the git trees lives in `./data`, so a single directory holds
the whole state of a deployment. `./data/mysql` must be empty the first time
MariaDB starts so that it can initialize the database there.

### Container settings

The container is configured entirely through environment variables in
`compose_example.yaml`; `contrib/settings_local.py` only supplies the defaults,
so there is no file to edit or mount.

| Variable | Default | Meaning |
|---|---|---|
| `GIT_REPO` | `/data/data.git` | bare repository the trees are fetched into |
| `DBLITE` | `/data/db.sqlite3` | SQLite database, used when `MARIADB_HOST` is unset |
| `MARIADB_DATABASE`/`_USER`/`_PASSWORD`/`_HOST`/`_PORT` | `kernel_tracker`… | MariaDB; setting `MARIADB_HOST` switches off SQLite |
| `STATIC_DIR` | `/data/static` | `collectstatic` target served at `/static/` |
| `PROCESSING_LOCK_FILE` | `/data/tmp/processing.lock` | lock file used by `cron update` |
| `TZ` | `UTC` | time zone of displayed timestamps and of the update schedule, e.g. `Asia/Shanghai`; also sets the container clock. An unknown name falls back to UTC |
| `DJANGO_SECRET_KEY` | dev key | **change before deploying** |
| `DJANGO_DEBUG` | `1` | set to `0` for production behaviour |
| `DJANGO_ALLOWED_HOSTS` | `*` | comma-separated host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://localhost:8080,http://127.0.0.1:8080` | extra origins for the CSRF check, needed when a proxy rewrites `Host` |
| `ADMIN_NAME` | `admin` | administrator created by `ensure_admin` when no superuser exists |
| `ADMIN_EMAIL` | empty | email of that account |
| `ADMIN_PASSWORD` | random | set it to pick the password yourself; otherwise one is generated |
| `PYGIT_WORKAROUNDS` | `1` | use external git for some operations |

A fresh deployment is ready to use: the bare repository is created on first
access, and `contrib/start` runs `ensure_admin`, which creates the first
account and writes its generated password to `./data/log/admin.log`, readable
by root only. Log in at `/admin/` and add trees there, then fetch them with
`cron update` or with the action on the tree list. To have that happen on its
own, enable it on the **Update schedule** page.

Both survive a container rebuild. Point the second one at wherever your
repositories live and add them by their in-container path:

```bash
LOCAL_GIT_DIR=/home/me/git podman-compose up -d
podman-compose exec kernel-tracker manage tree add -u -V local /git/myproject#main
```

## Management commands

| Command | Purpose |
|---|---|
| `manage tree add` | add a tracked git tree (`-u` upstream, `-d` downstream, `-V` vanilla) |
| `manage tree change` | change a tree's URL or rename it (not its kind) |
| `manage tree delete` | delete a tracked tree and its git remote (aliases `rm`, `remove`) |
| `manage tree alias` | add/remove alternate URLs for a tree |
| `manage tree show` | list tracked trees (aliases `ls`, `list`) |
| `manage cron update [tree ...]` | fetch and process new commits, for all trees or only the named ones |
| `manage cron daemon [--once]` | keep updating the trees on the schedule from the admin |
| `manage fsck` | consistency check |
| `manage ensure_admin` | create the administrator unless one already exists |

## Web UI and RPC API

| Path | Description |
|---|---|
| `/` | index, or setup page if no trees exist |
| `/tree/<name>/` | commit list for a tree |
| `/commit/<oid>/` | single commit view |
| `/series/<id>/`, `/filter/`, `/path/<tree>/<path>/` | filtered views |
| `/admin/` | Django admin: add and change trees, update them from the tree list, and enable scheduled updates |
| `/health` | health check |
| `/rpc/<method>/` | JSON-RPC endpoint |

RPC methods: `get_trees`, `get_tree`, `get_diff`, `get_series`,
`get_missing_fixes`, `get_missing_series`, `commit_list`, plus stubs
(`get_downstream`, `get_upstream`, `filter_backported`).

## Development tasks

```bash
make test       # pytest suite (104 tests, no containers needed)
make lint       # ruff check + black --check
make format     # ruff check --fix + black (reformats in place)
make help       # list all targets
```

## Current limitations

Phase 1 is upstream-only. Known gaps:

- `/author/<email>/` redirects to the index; author filtering needs a `Person`
  model (Phase 2).
- The `author` and `partial` filters in `dataview` are not implemented and will
  raise if requested.
- `get_downstream` / `get_upstream` are stubs; `filter_backported` returns its
  input unchanged.
- Series linking relies on a `Message-Id:` trailer, so projects merged through
  GitHub/GitLab pull requests get series without a link.
- The container build has not been verified end-to-end in an environment that
  can reach `docker.io`.
