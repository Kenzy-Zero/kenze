# Contributing to kenze

Thanks for wanting to help. kenze is a small, focused tool, and the goal is to
keep it that way: fast, one dependency at its core, and impossible to OOM.

## Local setup

kenze needs Python 3.9+.

```bash
git clone https://github.com/Kenzy-Zero/kenze
cd kenze
python -m pip install -e ".[dev]"   # editable install + pytest + ruff + build
```

That puts the `kenze` command on your PATH (editable, so code changes are live)
and installs the developer tools.

## Running the checks

The same three checks run in CI (Linux + Windows, Python 3.9 / 3.11 / 3.13):

```bash
ruff check src/kenze tests     # lint
pytest -q                      # the full test suite
python -m build                # the package still builds
```

A change should be green on all three before you open a pull request.

## Tests

Every command has tests in `tests/`. They exercise real behaviour end-to-end
(they actually read and write files with DuckDB), so they double as the release
regression:

- `test_transforms.py` — column/row ops (keep, drop, filter, cast, mask, dedup, …)
- `test_api.py` — the Python API + join / diff / split / pivot / eject
- `test_recipe.py` — the `.dq` recipe parser
- `test_assertions.py` — the data-quality guards (a failed check must write nothing)
- `test_ml.py` — the ML-prep transforms (scale, encode, onehot, traintest, …)
- `test_engine.py` — the never-OOM connection config
- `test_cli.py` — the installed `kenze` command, end-to-end
- `test_count.py` — `count` (value-counts / group-by)
- `test_sort.py` — `sort`
- `test_geojson.py` — GeoJSON read and write
- `test_report.py` — `report` (PDF / HTML output)
- `test_shell.py` — the interactive shell: command parity, key bindings, settings
- `test_value_complete.py` — ghost text and value autocomplete, including tests
  that drive a real `PromptSession` and press actual keys
- `test_csv_strict.py` — CSVs that break the standard, and the boundary between
  dropping a bad row and relaxing the parser
- `test_validate.py` — the schema gate and `--scaffold`

If you add or change a command, add or update its test. Prefer checking behaviour
against DuckDB reading the output (see the helpers in `tests/conftest.py`) rather
than hard-coding expected numbers.

## Benchmark

`bench/benchmark.py` proves the never-OOM claim (pandas OOMs at a memory budget,
kenze streams within it). Run it with `pip install pandas polars psutil` first.
It also runs in CI on every release.

## Design rules (please keep these)

- **One core dependency.** The engine is DuckDB (plus `psutil` for memory sizing
  and `prompt_toolkit` for the shell). Anything heavier ships as an optional
  extra (`kenze[polars]`, `kenze[arrow]`, …), never in the core.
- **Never OOM.** A whole recipe compiles to one streaming DuckDB query; new ops
  should follow that pattern (a SQL fragment in `ops.build_query`) so the
  memory-safety guarantee holds. Avoid pulling whole columns into Python.
- **ASCII-only output.** kenze must print cleanly on any console (including a
  Windows cp1252 terminal). No emoji or fancy unicode in command output.
- **Keep the core general.** Domain-specific behaviour belongs in an extension,
  not in the core commands.

## Submitting a pull request

1. Fork and branch off `main`.
2. Make the change, add/adjust tests, keep the three checks green.
3. Open the PR with a short description of the what and the why.

Small, focused PRs are easiest to review. If you're planning something larger,
open an issue first so we can talk through the approach.
