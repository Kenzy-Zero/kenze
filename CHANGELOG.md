# Changelog

All notable changes to kenze are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/).

## [0.8.3] - 2026-07-21

### Added
- **GeoJSON support.** `kenze convert data.csv -o data.geojson` writes GeoJSON —
  the geometry is built from lat/lon columns (auto-detected, or `--lat`/`--lon`) or
  from a WKT column (`--geom`). kenze now reads `.geojson` too (the geometry comes
  back as a WKT `geometry` column), so `convert map.geojson -o map.csv` works. Any
  command that writes a `.geojson` output gets it (e.g. `filter … -o out.geojson`).
- **Shell `convert`.** The `convert` command is now available inside the interactive
  shell (`convert out.xlsx`, `convert out.geojson`) — it was previously CLI-only.

## [0.8.2] - 2026-07-20

### Added
- **Shell: `eject` can save straight to a file.** `eject out.sql` / `eject out.py`
  (or `eject python out.py`) writes the code to that file from inside the shell — no
  need to exit and redirect. The format is inferred from the extension.

### Fixed
- **Shell: `eject` no longer silently falls back to SQL** on an unrecognized argument.
  Typing the terminal form (`eject recipe.dq --to python`) inside the shell now shows a
  clear usage hint instead of quietly printing SQL. `eject`, `eject python`,
  `eject --to python`, and `eject py` all work.

## [0.8.1] - 2026-07-17

### Docs
- Add a demo GIF to the README showing the interactive shell in action
  (load → filter → plot → run a 60-million-row file without ever running out of
  memory). Uses an absolute URL so it renders on both GitHub and the PyPI page.

## [0.8.0] - 2026-07-16 - "Model-Ready"

### Added (ML-prep - turn a clean file into a model-ready one, then hand it to scikit-learn / XGBoost; all pure DuckDB SQL, still never-OOM)
- **`scale`** - scale numeric columns for machine learning.
  `kenze scale data.parquet --cols amount,age --method minmax -o out`
  (or `--method zscore`). minmax maps to [0, 1]; zscore standardizes to mean 0 /
  std 1 (population std, matching scikit-learn's StandardScaler).
  Recipe: `scale: amount:minmax, age:zscore`. Shell: `scale amount minmax`.
- **`bin`** - bucket a numeric column into N bins, adding a `<col>_bin` column (1..N).
  `kenze bin data.parquet --cols age --into 5 --method uniform -o out`
  (`--method quantile` gives equal-count bins). Recipe: `bin: age:5, income:4:quantile`.
  Shell: `bin age 5`.
- **`encode`** - label-encode categorical columns to 0-based integers, in place.
  `kenze encode data.parquet --cols city,level -o out`. Alphabetical order, matching
  scikit-learn's LabelEncoder. Recipe: `encode: city, level`. Shell: `encode city`.
- **`onehot`** - one-hot encode categorical columns to 0/1 indicator columns (the
  original column is dropped). `kenze onehot data.parquet --cols city --max 50 -o out`.
  To stay memory-safe on a high-cardinality column, only the top-N values (by
  frequency) get their own column; the rest fold into `<col>_other`. Recipe:
  `onehot: city, brand:20`. Shell: `onehot city`.
- **`clip-outliers`** - cap extreme values (winsorize). `kenze clip-outliers data.parquet
  --cols amount --method iqr -o out` (or `--method pct`). iqr = Tukey's
  [Q1 - 1.5*IQR, Q3 + 1.5*IQR]; pct = [1st, 99th] percentile. Bounds come from
  `approx_quantile` (streaming). Recipe: `clip_outliers: amount:iqr`. Shell: `clip-outliers amount iqr`.
- **`traintest`** - split into train/test files. `kenze traintest data.parquet --ratio 0.8
  --seed 42 -o splits/` writes `train`/`test` files; the assignment is a deterministic
  hash of each row (+ seed), so a row can never land in both files or neither, and the
  split is reproducible. Time-based (leak-free for time-series):
  `kenze traintest data.parquet --by order_date --before 2026-01-01 -o splits/`.
  Also in the shell (`traintest splits/ ratio 0.8`).
- scale/bin/clip-outliers keep NULLs as NULL, handle a constant column, and give a clear
  message on a non-numeric column; encode keeps NULLs as NULL; onehot maps NULL to all-zeros.

### Improved
- `diff` now compares only the non-key columns present in **both** files, so diffing two
  files with partly-different schemas works instead of throwing an error.

### API
- `kenze.traintest(...)` is now importable, and any ML-prep step works through
  `kenze.sift(..., scale="amount:minmax", encode="city")`.

## [0.7.1] - 2026-07-15

### Improved (interactive shell — argument handling)
- **`plot` accepts a bare category** — `plot amount city` now works the same as
  `plot amount by city` (you no longer have to type `by`). It also **warns**
  instead of silently ignoring a bad `bins`/`top` value or leftover words.
- **Friendlier `filter`** — a natural, non-SQL condition like `filter status active`
  or `filter city = new york` is auto-repaired to valid SQL (`status = 'active'`) and
  the shell tells you how it read it. Real SQL (`amount > 100`) is untouched, and a
  condition it can't safely repair still shows the error and the quoting hint.
- **No more silent argument dropping** — `peek`/`history` warn on a non-numeric
  count, and `join`/`diff`/`pivot`/`unpivot`/`split`/`partition` warn about extra
  positional arguments instead of quietly ignoring them.

## [0.7.0] - 2026-07-15

### Added
- **`plot`** — quick ASCII charts right in the terminal / shell, to spot skew and
  dirty data without leaving the prompt. `kenze plot amount --by city` draws a bar
  chart of `sum(amount)` per city; `kenze plot amount` draws a histogram (numeric)
  or top value-counts (text). In the shell it charts the **live pipeline**, so you
  can `filter` then `plot` the result. Smooth Unicode bars where the console
  supports them, ASCII `#` fallback otherwise.
- **Excel (`.xlsx`) read and write** — read a workbook as input and write one as
  output anywhere kenze takes a file (`kenze convert big.parquet -o report.xlsx`,
  `kenze filter data.xlsx --where "amount>0" -o out.csv`). Powered by DuckDB's
  `excel` extension — no extra Python dependency.
- **`--skip N` / `load … skip N`** — skip junk preamble rows (comment banners,
  blank lines) before the real CSV header in messy exports. The interactive shell
  also **auto-detects** obvious preamble on `load` and skips it for you (a
  "smart import"), telling you what it did.
- **`history`** — a local run ledger (`~/.kenze/history.jsonl`). `kenze history`
  shows recent runs (input → output, rows, time). Disable with `--no-history` or
  `KENZE_NO_HISTORY=1`.

### Changed
- Minimum DuckDB is now **1.2** (up from 0.10) — required for `read_xlsx`/Excel
  write and the CSV `strict_mode` used by `--skip`.
- Loading a folder or a non-existent path now gives a clear message ("that's a
  folder, point at a file …") instead of a cryptic DuckDB catalog error.

## [0.6.1] - 2026-07-15

### Fixed
- **Docs links** — `SHELL.md` references in the README are now absolute GitHub URLs
  so they resolve correctly on the PyPI project page (relative links 404'd there).
- Housekeeping on the `LICENSE` file (copyright line); no functional change.

## [0.6.0] - 2026-07-15

### Added
- **Interactive shell** — run `kenze` with no arguments (or `kenze shell`) and land
  in a live session: load a file once, stack simple steps that **preview as you go**,
  then run the pipeline to a file or save it as a recipe. Highlights:
  - a `/` command menu, schema-aware **TAB autocomplete** of your file's columns,
    command history, and a colour theme;
  - **every CLI capability, in the shell** — inspect (`peek`/`schema`/`count`/`stats`/
    `check`/`validate`), shape (`filter`/`keep`/`drop`/`rename`/`cast`/`fillna`/`mask`/
    `dedup`/`clip`/`sample`/`head`), combine/reshape/split (`join`/`diff`/`pivot`/
    `unpivot`/`split`/`partition`), guards (`assert`/`assert-unique`/`assert-not-null`),
    and output (`run`/`save`/`dryrun`/`eject`/`sql`);
  - session helpers: `open` a saved recipe to view/edit/run it, `set` for
    memory/threads/skip-bad/temp/disk-check, `pwd`/`cd` for the output folder,
    `undo`/`reset`/`steps`, and `recipe` for the format reference;
  - `run` options in-shell: `append`, `errors <file>`, `log <file>`.
- **`prompt_toolkit` is now a core dependency**, so the shell works out of the box
  with a plain `pip install kenze`.
- Documentation: a full shell guide in **SHELL.md**.

### Notes
- Running `kenze` with no arguments now opens the shell (previously it printed usage).
  The one-line CLI is unchanged.

## [0.5.0] - 2026-07-14

### Added
- **Recipe assertions** — `assert: row_count > 0`, `assert_unique: id`,
  `assert_not_null: id, email` inside a `.dq` recipe. They run *before* anything
  is written, so a failed check aborts with no output. Build data-quality tests
  right into your cleaning recipe.
- **`unpivot`** — reshape wide to long (the complement of `pivot` / a "melt").
- **Multi-file glob schema unification** — reading `sales_*.csv` (or parquet/json)
  now uses `union_by_name`, so a column mismatch between files no longer crashes
  the run.
- **`--threads N`** — cap the threads DuckDB uses.
- **`--log`** now also records the input and output schema (light lineage).

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
