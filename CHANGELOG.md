# Changelog

All notable changes to kenze are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/).

## [0.9.4] - 2026-07-25

### Fixed
- **`--n` no longer fails with "ambiguous option" on Python 3.9 and 3.11.**
  argparse treats an unrecognised long option as an abbreviation, so `--n`
  matched both `--no-disk-check` and `--no-history` and the parse failed before
  the subcommand ever saw the flag. Python 3.13 tolerated it, which is why it
  was not caught locally.
  - This affected **`peek --n`, `sample --n` and `head --n` in every previous
    release**, not only the `filter --n` and `dedup --n` added in 0.9.3.
  - Fixed by disabling argparse's option abbreviation (`allow_abbrev=False`) on
    the main parser and every subcommand. Long options must now be written in
    full, which was already true of every documented example.
  - A regression test now runs all five `--n` commands through the real CLI.

## [0.9.3] - 2026-07-25

### Added
- **`--n` on `filter` and `dedup`** - cap the result so you can check an operation
  before writing the whole thing. Requested by a user who wanted to confirm a
  filter was right without piping the result through a full `kenze sql` query
  with a `LIMIT` clause.
  - `kenze filter sales.parquet --where "amount > 100" --n 20 -o -` prints the
    first 20 matching rows to the terminal.
  - `kenze dedup users.csv --on id --n 20 -o -` does the same for deduplication.
  - The condition is still evaluated against the entire file; `--n` only limits
    how many of the matching rows come back, so a limit can never return a row
    that does not match.
  - `--n` matches the flag already used by `sample` and `head`.
  - The interactive shell already supported this by stacking `filter` then `head`,
    and continues to show a live preview after every step.

## [0.9.2] - 2026-07-23

### Added
- **A `docs/` folder** with detailed guides: a full **[Python API reference](docs/python-api.md)**
  (every public function — exact signature, arguments, return value, example),
  a **[reports guide](docs/report.md)**, and an **[index](docs/index.md)** that maps
  all the docs. The README now links them prominently.
- **`kenze.count` in the Python API** — the value-counts / group-by function is now
  a documented, exported part of `import kenze` (alongside `sift`, `sql`, `count`,
  `to_polars`, and the rest).

## [0.9.1] - 2026-07-23

### Added
- **`count` - no-SQL value-counts / group-by count.** `kenze count sales.csv city`
  counts rows per value (biggest first), printed or written with `-o`.
  - `--top N` keeps only the top N groups (`kenze count sales.csv city --top 10`).
  - `--distinct col` counts *unique* values of another column per group
    (e.g. unique users per city) instead of rows.
  - `count city category` groups by more than one column.
  - Also in the shell: `count` alone counts rows; `count city` gives value-counts.
  - Pairs with `report`: `kenze count data.csv city --top 10 -o c.csv` then
    `kenze report c.csv -o out.pdf` - a counts report with no SQL.
- **`sort` - order rows by column(s), a real pipeline step.** `kenze sort sales.csv
  --by revenue --desc --top 10 -o top.csv`. `--by` takes one or more columns
  (add `:desc` per column), `--desc` sorts all descending, `--top N` keeps the
  first N (so **sort + top = top N**). Works as a recipe step and stacks in the
  shell pipeline (`load ... -> sort revenue desc -> head 10 -> report out.pdf`).

## [0.9.0] - 2026-07-23

### Added
- **`kenze report` — turn a data file into a styled PDF or HTML report.** Point it
  at a file and it auto-detects your columns (a label, a headline "revenue" metric,
  a growth/percent column) and lays out KPI tiles + a ranked table. The summary is
  computed with DuckDB aggregates over the **whole** file (never-OOM); the detail
  table is a bounded top-N (`--limit`), so a 60M-row file still renders instantly.
  - `kenze report data.csv -o out.pdf` — built-in theme to PDF (or `-o out.html`).
  - `--per-row --format pdf -o docs/` — **one document per row** (batch / mail-merge).
  - `--scaffold` — writes a starter HTML template *pre-filled with your column names*,
    so you never guess placeholders (`{{ r.col }}`, `{{ stats.col.sum }}`, `{{ meta.title }}`).
  - `--template mine.html` — bring your own HTML (Jinja2); `--theme report|scorecard`;
    `--set title=... client=... currency=... period=...` for the headings.
  - Available in the **interactive shell** too: `report out.pdf`.
- **PDF with no heavy install.** HTML output needs only Jinja2 (`pip install "kenze[report]"`).
  PDF renders that HTML with the system Chrome/Edge (pixel-perfect, zero extra
  install), and falls back to WeasyPrint if it's installed.

## [0.8.5] - 2026-07-21

### Added
- **Guided shell: the bottom toolbar now tells you what to type next.** As you
  type, it shows the next expected argument with an example (e.g. `filter` ->
  `next: a condition   e.g. filter amount > 100`), and flips to `[OK] press Enter
  to run` once the line is complete. With nothing loaded it points you to `load`;
  with a file loaded it nudges you toward a step or an output. Every command has a
  hint. So you don't have to remember any command's shape.
- **Smarter TAB completion.** Beyond commands, columns and file paths, TAB now
  completes option keywords for `run`/`convert` (`append`/`errors`/`log`,
  `geom=`/`lat=`/`lon=`), `set` settings, and the type/method after a colon
  (`cast id:VARCHAR`, `scale x:zscore`, `clip-outliers a:iqr`).

## [0.8.4] - 2026-07-21

### Added
- **`convert` reads GeoJSON-geometry columns.** When writing GeoJSON, the geometry
  column (`--geom`, or an auto-detected `geometry`/`geom`/`coordinates` column) may
  now hold either WKT (`POINT(...)`) or a GeoJSON geometry object (`{"type":...}`) —
  kenze sniffs the value and parses it accordingly. So a spreadsheet whose column
  holds GeoJSON polygons converts straight to a real `.geojson`.

### Fixed
- **Shell `convert` no longer silently overwrites your loaded file.** Passing the
  terminal form inside the shell (`convert input -o output`) now shows a clear
  message ("in the shell the file is already loaded — convert takes just the
  OUTPUT") instead of mis-reading the input path as the output. It also refuses to
  write to the exact file you loaded, so your source can't be clobbered by accident.

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
