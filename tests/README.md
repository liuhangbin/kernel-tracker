# kernel-tracker Test Suite

## Test Structure

### Unit Tests (pytest)

Located in `tests/unit/`. Run with `uv run pytest tests/unit/`.

| File | Description |
|------|-------------|
| `test_fields.py` | OidField validation (format, length, hex chars) |
| `test_patch.py` | Unified diff parser (single/multi file, rename, delete, empty) |
| `test_models.py` | Model string representations, constraints, helper methods |
| `test_rpctranslate.py` | JSON-RPC translation layer (types, validation, errors) |
| `test_dataview.py` | commit_list filters: tree, notin, path/excl, fixes, ordering |
| `test_views.py` | Web view smoke tests (index, tree, filter, path, series, commit, health) |
| `test_rpc.py` | get_missing_fixes / get_missing_series graph building |
| `test_admin.py` | The tree list action starts `cron update` detached, and refuses to when one is running |
| `test_schedule.py` | Update schedule row: singleton, defaults, due times, timezone |

### Pipeline Test (pytest)

`test_pipeline.py` builds a real git repository in a temporary directory and
runs the `tree add` and `cron update` management commands against it. It
checks that commits, fix references, files, series and vanilla versions are
recorded. Repository helpers live in `gitrepo.py`.

`test_cron.py` checks which trees `cron update` processes with and without
names on the command line. `test_cron_daemon.py` drives the scheduled loop
with the update patched out and `time.sleep` standing in for waiting: nothing
runs while the schedule is disabled, a due update runs once instead of every
round, one already running is skipped, and a failing one does not stop the
loop.

`test_tree.py` exercises `tree delete` against a real (empty) tracker
repository: the tree row and git remote are removed, commits survive, the
confirmation prompt aborts on a mismatched name and the vanilla tree is
protected while other trees exist.

### Integration Tests (shell, TAP format)

Located in `tests/*.sh`. Run inside the container via `tests/run`.

| File | Description |
|------|-------------|
| `001-init.sh` | Add vanilla upstream tree, verify it exists in DB |
| `002-tree-show.sh` | List configured trees via management command |
| `003-commit-count.sh` | Verify commits are processed after tree update |
| `004-commit-trees.sh` | Verify commits are associated with correct tree |
| `005-series-detection.sh` | Verify series model is accessible |
| `006-health.sh` | Verify health view endpoint exists |

## Running Tests

### Unit tests (local)
```bash
uv run pytest tests/unit/ -v
```

### Integration tests (container)
```bash
make integration-test
```

### All tests (container, debug mode)
```bash
make debug
```
