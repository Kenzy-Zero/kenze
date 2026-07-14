# Changelog

All notable changes to kenze are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-07-14

### Added
- `--dry-run` — show the compiled query and output schema without executing.
- `--errors PATH` — quarantine malformed CSV rows to a file (with line/column
  diagnostics) instead of failing, while the good rows keep flowing.
- `--append` — append to an existing csv/json output instead of overwriting.
- `--source-format delta | iceberg` — read Delta Lake and Apache Iceberg tables.
- `kenze init [recipe.dq] [--input FILE]` — scaffold a starter recipe, pre-filled
  with a file's columns.
- Python dataframe bridges: `kenze.to_polars(...)`, `kenze.to_arrow(...)`,
  `kenze.to_df(...)` — hand cleaned data straight to a fast in-memory frame.
- Optional extras: `pip install kenze[polars]`, `kenze[arrow]`, `kenze[pandas]`,
  or `kenze[all]`.
- Trusted Publishing workflow for signed, tokenless releases via GitHub Actions.

## [0.3.1] - 2026-07-14

### Added
- Project metadata polish: PyPI badges, project links, expanded classifiers.
- `CHANGELOG.md` and continuous-integration workflow.

### Notes
- No functional changes from 0.3.0; this release refreshes the packaging and
  documentation surface.

## [0.3.0] - 2026-07-14

The first release under the name **kenze**.

### Added
- Inspecting: `profile`, `peek`, `stats`, `check`, `validate`.
- Column operations: `keep`, `drop`, `rename`, `cast`, `fillna`, `mask`.
- Row operations: `filter`, `dedup`, `sample`, `head`, `clip`, `convert`.
- Combining and reshaping: `join`, `diff`, `pivot`.
- Splitting: `split`, `partition` (Hive layout).
- Power tools: `sql` (window functions and more), `eject` (to SQL or Python).
- Recipes (`.dq`) with `${VAR}` / `{{ VAR }}` templating; `run` and `recipe`.
- A Python API: `kenze.sift(...)`, `kenze.run(...)`, `kenze.sql(...)`, and more.
- Cloud storage support (`s3://`, `gs://`, Azure) via DuckDB httpfs.
- Global options: `--memory-limit`, `--temp-dir`, `--no-disk-check`,
  `--skip-bad-lines`, `--log`, `--quiet`.
- Automatic never-OOM memory sizing (psutil is a core dependency), disk-spill,
  a pre-flight disk-space check, and atomic writes.
