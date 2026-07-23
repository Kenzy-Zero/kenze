# kenze — Project Documentation

Big-file data preparation that never runs out of memory. No SQL required.

Version 0.9.0

---

## Table of contents

1. Overview
2. Design philosophy
3. Installation
4. Quick start
5. Core concepts
6. Command reference
   - 6.1 Inspecting data
   - 6.2 Column operations
   - 6.3 Row operations
   - 6.4 Combining and reshaping
   - 6.5 Splitting and partitioning
   - 6.6 Power tools and interoperability
   - 6.7 Recipes
7. Recipes in depth
8. The Python API
9. Working with cloud storage
10. Global options
11. The memory model (how it never runs out of memory)
12. Supported formats
13. Where kenze stops, by design
14. Troubleshooting
15. Versioning and releases
16. Roadmap
17. License

---

## 1. Overview

kenze is a command-line tool for cleaning, filtering, and reshaping data files
that are too large to open comfortably in pandas. It is a thin, friendly layer
over DuckDB. DuckDB performs the actual work — streaming reads, spilling to disk
when needed, and using every CPU core — while kenze provides a small set of
memorable commands and automatically configures memory so that a job does not
crash on a machine with limited RAM.

The tool is intended for the analyst or engineer who has a file that is larger
than memory, does not want to write SQL, and simply wants the operation to
complete without an out-of-memory error.

A single identity is used throughout:

- Install with `pip install kenze`
- Run with the `kenze` command
- Import in Python with `import kenze`

There is one required system concept to understand and nothing else: point kenze
at a file, name an operation, and name an output. Everything follows from that.

kenze can be used two ways, over the same engine:

- **Interactively.** Run `kenze` with no arguments to enter a live shell: load a
  file once, stack steps that preview as you go, then run or save the result.
  Every command below is available in the shell, along with a `/` command menu and
  column autocomplete. The shell is documented in full in `SHELL.md`.
- **As a one-line CLI.** `kenze <command> <input> -o <output>` — ideal for scripts,
  cron, and pipelines. This document is the reference for that form.

---

## 2. Design philosophy

kenze is built around a small number of firm principles. These are deliberate
constraints; they define what the tool is and, equally, what it is not.

**One streaming pass.** A whole recipe compiles to a single DuckDB query. The
tool does not write a series of intermediate temporary files between steps. This
is what makes a multi-step transform both fast and memory-light: the data is
read once and written once.

**Never run out of memory.** The memory ceiling is set automatically to a
fraction of the memory that is currently free, not the total installed memory.
DuckDB is configured to spill to disk when a job genuinely needs more space than
that ceiling allows. The practical result is that pointing the tool at a file
larger than RAM does not crash it.

**No SQL for the common path.** The everyday operations — keep, drop, filter,
rename, cast, deduplicate, sample — are plain verbs. SQL is available as a
deliberate escape hatch for the cases that genuinely need it, but it is never a
requirement for routine work.

**A small, general core.** The core commands operate on any file and any column.
The tool is not specialised for one domain. Domain-specific behaviour, if it is
ever added, belongs in an optional extension and never in the core.

**Few dependencies.** kenze requires only DuckDB and psutil. This keeps the
install fast, the surface area small, and the tool easy to trust and to reason
about.

**Cross-platform, always-printable output.** All console output is plain ASCII
so that it renders correctly on any terminal, including older Windows consoles.

**Safe writes.** Every write is atomic: output is written to a temporary file
and renamed into place only on success. A cancelled or failed run never leaves a
half-written output file behind.

---

## 3. Installation

### Requirements

- Python 3.9 or newer
- The dependencies `duckdb` (1.2 or newer), `psutil` and `prompt_toolkit`,
  installed automatically

### Standard install

```
pip install kenze
```

This installs the library and the `kenze` command-line program.

### Isolated install

If you prefer an isolated environment that also manages your PATH:

```
python -m pipx install kenze
```

### From source

```
git clone <repository-url> kenze
cd kenze
pip install -e .
```

An editable install (`-e`) means changes to the source are picked up
immediately, which is convenient during development.

### If the `kenze` command is not found

When `pip` installs a command-line program, it places the executable in a
"scripts" directory. On some systems that directory is not on your PATH, so the
shell cannot find the command even though installation succeeded. This affects
every pip-installed tool, not just kenze. There are three remedies:

1. Run it as a module, which never depends on PATH:
   ```
   python -m kenze --help
   ```
2. Reinstall Python from python.org and enable the option "Add python.exe to
   PATH" during installation.
3. Use `pipx`, which manages PATH for you.

---

## 4. Quick start

Inspect a file without loading it fully:

```
kenze profile sales.parquet
kenze peek sales.parquet
kenze stats sales.parquet
```

Perform a single operation:

```
kenze filter sales.parquet --where "amount > 100" -o large.csv
kenze keep   sales.parquet --cols id,city,amount  -o small.csv
```

Chain operations in a recipe file and run them in one pass:

```
kenze run clean.dq
```

Use it from Python:

```python
import kenze
kenze.sift("sales.parquet", "clean.csv",
           keep=["id", "city", "amount"], filter="amount > 0", sample=50000)
```

---

## 5. Core concepts

**Input and output.** Most commands take a single input path as the first
argument and require an output path via `-o` or `--output`. Formats are detected
from file extensions.

**The single-query model.** When you chain steps in a recipe, kenze does not run
each step separately. It composes one SQL query that expresses the entire
pipeline and executes it as one streaming operation.

**Automatic memory management.** You do not configure memory unless you want to.
The default sizing is derived from currently free RAM. See section 11 for the
full model and section 10 for the `--memory-limit` override.

**Atomic output.** Writes go to a temporary file and are renamed into place on
success. If a run is cancelled with Ctrl+C or fails partway, the destination
file is never corrupted.

**Standard input and output.** A path of `-` means standard input (for a source)
or standard output (for a destination), which lets kenze participate in Unix
pipelines.

---

## 6. Command reference

The general form of a transforming command is:

```
kenze <command> <input> [options] -o <output>
```

Inspecting commands print to the screen and do not require an output path.

### 6.1 Inspecting data

#### profile

Print the schema and exact row count of a file. For Parquet this reads only the
file's metadata, so it is effectively instant even for very large files.

```
kenze profile sales.parquet
```

#### peek

Show the first rows of a file as an aligned table, together with each column's
type and the number of nulls found in the previewed sample. This is a quick,
zero-dependency way to see what you are working with before transforming it.

```
kenze peek sales.csv --n 20
```

Options:
- `--n N` — number of rows to preview (default 20).

#### stats

Print a per-column statistical summary: minimum, maximum, approximate number of
distinct values, and null percentage. This is computed by DuckDB's summarizer
and works on files larger than memory.

```
kenze stats sales.parquet
```

#### plot

Draw a quick ASCII chart in the terminal, to spot skew, outliers and dirty data
without leaving the prompt or opening another tool. With `--by`, it draws a bar
chart of an aggregate per category; without it, a numeric column becomes a
histogram and a text column becomes top value-counts.

```
kenze plot sales.csv amount --by city      # bar chart: sum(amount) per city
kenze plot sales.csv amount --bins 15      # histogram of a numeric column
kenze plot sales.csv city                  # top value-counts of a text column
```

Options:
- `--by COL` — a category column; the chart shows `agg(column)` for each value.
- `--agg sum|count|avg|min|max|median` — the aggregate for `--by` (default `sum`,
  or `count` when the charted column is non-numeric).
- `--bins N` — number of histogram bins (numeric column, no `--by`; default 20).
- `--top N` — the maximum number of bars to show (default 20).
- `--width N` — bar width in characters (default 48).

Bars use smooth Unicode blocks where the console supports them and fall back to a
plain ASCII `#` bar otherwise. In the interactive shell, `plot` charts the current
pipeline, so you can `filter` and then `plot` the filtered result.

#### check

A pre-flight integrity scan. It reports how many rows are readable and, for CSV
inputs, how many rows would be rejected as malformed. Use it before a long job
to confirm a file is intact.

```
kenze check sales.csv
```

If malformed rows are reported, you can process the file anyway with the global
`--skip-bad-lines` flag (see section 10).

#### validate

Check a file against a target schema described in JSON, and exit with a non-zero
status if the file does not conform. This makes kenze usable as a gate in
automated pipelines and scheduled jobs.

```
kenze validate sales.csv --schema schema.json
```

The schema file has the form:

```json
{
  "columns": { "id": "VARCHAR", "amount": "DOUBLE" },
  "not_null": ["id"]
}
```

The command reports every column whose type does not match, every required
column that is absent, and any nulls found in columns listed under `not_null`.
It exits 0 when the file conforms and 1 when it does not.

### 6.2 Column operations

#### keep

Keep only the named columns, dropping all others.

```
kenze keep sales.parquet --cols id,city,amount -o small.csv
```

#### drop

Remove the named columns, keeping all others.

```
kenze drop users.csv --cols email,phone -o clean.parquet
```

#### rename

Rename one or more columns. The mapping is a comma-separated list of
`old:new` pairs.

```
kenze rename sales.csv --map "amount:total,ts:timestamp" -o out.csv
```

#### cast

Change the type of one or more columns. The specification is a comma-separated
list of `column:TYPE` pairs, where TYPE is any DuckDB type name. A common use is
forcing an identifier or postal code to remain text so that leading zeros are
not lost.

```
kenze cast users.csv --types "zip:VARCHAR,id:VARCHAR" -o out.parquet
```

#### fillna

Replace null values in one or more columns with a given value. The specification
is a comma-separated list of `column:value` pairs. A value that looks like a
number is treated as a number; otherwise it is treated as text.

```
kenze fillna users.csv --with "city:Unknown,score:0" -o out.csv
```

#### mask

Mask the contents of sensitive columns, in place, so that a dataset can be shared
or analysed without exposing personal data.

```
kenze mask users.csv --cols email,ssn,phone --method hash -o safe.csv
```

Options:
- `--method hash` — replace each value with an irreversible hash (default).
- `--method redact` — replace each value with a fixed placeholder.
- `--method null` — replace each value with null.

**Machine-learning prep (model-ready).** The next five commands turn a clean file into one
you can hand straight to scikit-learn / XGBoost. Every one is pure DuckDB SQL — no numpy or
scikit-learn dependency — so they keep the never-OOM guarantee on files bigger than RAM.

#### scale

Scale numeric columns for a model. `minmax` maps values to [0, 1]; `zscore` standardizes to
mean 0 / standard deviation 1 (population standard deviation, matching scikit-learn's
StandardScaler). NULLs stay NULL.

```
kenze scale data.parquet --cols amount,age --method minmax -o out.parquet
```

#### bin

Bucket a numeric column into N bins, adding a `<col>_bin` column (values 1..N). `uniform` =
equal-width buckets; `quantile` = equal-count buckets. NULLs stay NULL.

```
kenze bin data.parquet --cols age --into 5 --method uniform -o out.parquet
```

#### encode

Label-encode categorical columns to 0-based integers, in place, in alphabetical order —
matching scikit-learn's LabelEncoder.

```
kenze encode data.parquet --cols city,level -o out.parquet
```

#### onehot

One-hot encode categorical columns into 0/1 indicator columns; the original column is
dropped. Only the top `--max` values (by frequency) get their own column and the rest fold
into `<col>_other`, so a high-cardinality column can't explode into thousands of columns.

```
kenze onehot data.parquet --cols city --max 50 -o out.parquet
```

#### clip-outliers

Cap extreme values (winsorize). `iqr` clips to Tukey's fence
[Q1 − 1.5·IQR, Q3 + 1.5·IQR]; `pct` clips to the [1st, 99th] percentile. Bounds are read
with `approx_quantile`, so it stays memory-safe on huge columns.

```
kenze clip-outliers data.parquet --cols amount --method iqr -o out.parquet
```

### 6.3 Row operations

#### filter

Keep only the rows that match a condition. The condition is a boolean expression
evaluated by DuckDB, so it supports the full range of comparison and function
syntax.

```
kenze filter sales.parquet --where "amount > 100 AND city = 'London'" -o big.csv
```

#### dedup

Remove duplicate rows. By default the entire row must match to be considered a
duplicate. Alternatively, provide one or more key columns and only the first row
for each combination of key values is kept.

```
kenze dedup users.csv --on id -o unique.parquet
kenze dedup users.csv --on all -o unique.parquet
```

Options:
- `--on cols` — key column(s), comma-separated; or `all` for whole-row (default).

#### sample

Keep a random sample of N rows.

```
kenze sample sales.parquet --n 50000 -o sample.csv
```

#### head

Keep the first N rows.

```
kenze head sales.parquet --n 100 -o first.csv
```

#### clip

Keep only the rows whose coordinates fall inside a geographic bounding box. The
box is given as `min_lon,min_lat,max_lon,max_lat`. Latitude and longitude
columns are detected automatically from common names.

```
kenze clip points.parquet --bbox 51.0,25.0,56.5,26.5 -o region.parquet
```

Note: if any bounding-box value is negative, attach it with an equals sign so the
shell does not mistake it for an option, for example `--bbox=-10,35,5,45`.

#### convert

Rewrite a file in a different format, chosen by the output extension, without any
other transformation. Supports CSV, TSV, Parquet, JSON, Excel (`.xlsx`) and
GeoJSON (`.geojson`), plus their `.gz` variants.

```
kenze convert sales.parquet -o sales.csv
kenze convert sales.csv     -o report.xlsx
```

**GeoJSON.** Writing a `.geojson` needs a geometry. kenze builds it from a lat/lon
pair (column names like `latitude`/`longitude`/`lat`/`lon` are auto-detected) or a
geometry column (named `geometry`/`geom`/`coordinates`, or given with `--geom`).
That geometry column may hold either WKT (`POINT(...)`) **or** a GeoJSON geometry
object (`{"type":"Polygon",...}`) — kenze detects which and parses it accordingly,
so a spreadsheet of GeoJSON polygons converts straight to a `.geojson`. Reading a
`.geojson` flattens the geometry into a WKT `geometry` column so it behaves like
any other table.

```
kenze convert places.csv     -o places.geojson              # auto lat/lon
kenze convert places.csv     -o places.geojson --lat Y --lon X
kenze convert layer.geojson  -o layer.parquet               # geometry -> WKT
```

Any command that writes a `.geojson` output gets the same treatment (for example
`kenze filter places.csv --where "amount > 0" -o hot.geojson`). GeoJSON support
uses DuckDB's `spatial` extension, loaded automatically on first use.

### 6.4 Combining and reshaping

#### join

Join two files on one or more key columns.

```
kenze join orders.csv users.parquet --on user_id -o joined.parquet
```

Options:
- `--on cols` — key column(s) present in both files.
- `--how inner|left|right|full` — the join type (default inner).

Note: the key column(s) appear once in the output. If the two files share
non-key columns with the same name, rename them first to avoid ambiguity.

#### diff

Compare two versions of a dataset on a key and report how many rows were added,
removed, and changed. Optionally write the affected keys to a file.

```
kenze diff yesterday.csv today.csv --on id -o changes.csv
```

A row is "added" if its key is present in the new file only, "removed" if it is
present in the old file only, and "changed" if the key exists in both but any
non-key value differs.

#### pivot

Reshape data from long form to wide form. The distinct values of one column
become new columns, and a second column is aggregated to fill them.

```
kenze pivot sales.csv --on city --values amount --agg sum --group region -o wide.csv
```

Options:
- `--on col` — the column whose values become new columns.
- `--values col` — the column to aggregate.
- `--agg sum|count|avg|min|max|median` — the aggregation (default sum).
- `--group cols` — the row-identity columns to retain (optional).

#### unpivot

The complement of `pivot`: reshape wide to long by folding several columns into a
name column and a value column (a "melt"). Columns you don't fold are kept.

```
kenze unpivot wide.csv --cols jan,feb,mar --name month --value sales -o long.csv
```

Options:
- `--cols cols` — the columns to fold.
- `--name NAME` — the new name column (default `name`).
- `--value NAME` — the new value column (default `value`).

### 6.5 Splitting and partitioning

#### split

Write one output file per distinct value of a column. Useful for breaking a
single large file into per-category files.

```
kenze split sales.parquet --by city -o by_city/
```

Options:
- `--by col` — the column to split on.
- `--format csv|parquet|json` — the format of the output files (default csv).

Each value is turned into a safe filename. To guard against accidentally
creating an enormous number of files, splitting stops with an error if the
column has more than a few thousand distinct values; use `partition` for that
case.

#### partition

Write a directory of files in the Hive partitioning layout, where each partition
column becomes a nested `column=value` folder. This is the layout expected by
modern data lake tooling.

```
kenze partition sales.parquet --by year,month -o lake/
```

Options:
- `--by cols` — one or more partition columns.
- `--format parquet|csv` — the output format (default parquet).

#### traintest

Split a dataset into `train` and `test` files (for machine learning). Each row is assigned
by a deterministic hash of its values (plus the seed), so the split is reproducible and a
row can never land in both files or neither.

```
kenze traintest data.parquet --ratio 0.8 --seed 42 -o splits/
```

For time-series data, use a time-based split — a random split would leak future information
into the past, inflating your accuracy:

```
kenze traintest data.parquet --by order_date --before 2026-01-01 -o splits/
```

Options:
- `--ratio R` — the train fraction (default 0.8).
- `--seed N` — seed for the deterministic assignment (default 42).
- `--by col` / `--before value` — time-based split: rows with `col` < `value` go to train, the rest to test.
- `--format parquet|csv|json` — the output format (default parquet).

### 6.6 Power tools and interoperability

#### sql

Run any DuckDB SQL statement. This is the deliberate escape hatch for operations
that do not fit a simple verb, such as window functions, complex aggregations,
and advanced reshaping. Files can be referenced directly by path inside the
query.

```
kenze sql "SELECT id, amount, sum(amount) OVER (ORDER BY id) AS running_total FROM 'sales.parquet'" -o out.csv
```

If `-o` is omitted, the first rows of the result are printed to the screen.

A window function performs a calculation across a set of rows that are related to
the current row, without collapsing them the way a GROUP BY does. Typical
examples are a running total, the value of the previous row, a rank, or a moving
average. Because these are too varied to reduce to a single command, they are
expressed through `sql`.

#### eject

Convert a recipe into standalone, copy-pasteable code, so that you can prototype
quickly in kenze and then move the logic into a production codebase without being
locked in.

```
kenze eject clean.dq --to sql
kenze eject clean.dq --to python
```

Options:
- `--to sql` — emit the equivalent DuckDB SQL (default).
- `--to python` — emit a small runnable Python snippet using DuckDB directly.

#### history

Show recent runs, recorded in a local ledger at `~/.kenze/history.jsonl`. Each
successful transform, recipe run, join, pivot, split and so on appends one line
(input, output, row count and timing), giving a lightweight, always-on audit trail
of what you have run.

```
kenze history            # the last 20 runs
kenze history --n 50     # the last 50
```

Recording is silent and best-effort. Disable it for a single run with
`--no-history`, or globally with the environment variable `KENZE_NO_HISTORY=1`.

### 6.7 Recipes

#### run

Execute a recipe file (see section 7).

```
kenze run clean.dq
kenze run clean.dq --set DAY=2026-07-14
```

Options:
- `--set KEY=VALUE` — provide a value for a recipe variable; may be repeated.

#### init

Scaffold a starter recipe file. With `--input`, it reads the file's columns and
pre-fills them so you only have to delete what you don't want.

```
kenze init clean.dq --input sales.csv
```

#### recipe

Print the recipe file format and every valid step, as a built-in cheat sheet.

```
kenze recipe
```

---

## 7. Recipes in depth

A recipe is a plain text file, conventionally with a `.dq` extension, that
describes a pipeline as a set of `key: value` lines. It runs as a single
streaming pass, exactly as if you had chained the equivalent commands.

Example:

```
# clean.dq
input:  data/sales.parquet
keep:   [id, city, amount, zip]
types:  zip:VARCHAR
filter: amount > 0
fillna: city:Unknown
dedup:  id
sample: 50000
output: out/clean.csv
```

### Rules

- One `key: value` per line.
- A list is written in square brackets: `[a, b, c]`.
- A line beginning with `#` is a comment; a `#` outside of quotes ends a line.
- `input` and `output` are required. All other steps are optional and may appear
  in any order.

### Available steps

| Step | Meaning |
| --- | --- |
| `input` | Source file (required). CSV, Parquet, JSON, a `.gz` variant, or a remote path. |
| `keep` | Keep only these columns. |
| `drop` | Remove these columns. |
| `filter` | Keep only rows matching a condition. |
| `bbox` | Keep only rows inside a lon/lat box: `minlon,minlat,maxlon,maxlat`. |
| `types` | Cast columns: `col:TYPE, col:TYPE`. |
| `fillna` | Replace nulls: `col:value, col:value`. |
| `mask` | Mask columns: `col, col`. |
| `mask_method` | `hash` (default), `redact`, or `null`. |
| `rename` | Rename columns: `old:new, old:new`. |
| `dedup` | Drop duplicates by a key column, or `all`. |
| `sample` | Keep N random rows. |
| `head` | Keep the first N rows. |
| `assert` | Fail the run unless a condition on `row_count` holds, e.g. `row_count > 0`. |
| `assert_unique` | Fail if the listed column(s) contain duplicates. |
| `assert_not_null` | Fail if the listed columns contain nulls. |
| `output` | Destination file (required). |

Assertions run *before* anything is written, so a failed check aborts the run with
no output. You can list several `assert` / `assert_unique` / `assert_not_null` lines
to build data-quality tests directly into a recipe.

Every step name is identical to the corresponding command name. Learning the
commands teaches the recipe format at the same time.

### Variables

A recipe value can contain variables written as `${NAME}` or `{{ NAME }}`. Their
values come from `--set` arguments or from the environment, which lets the same
recipe run on a schedule with a changing date or path.

```
input: data/sales_${DAY}.parquet
```

```
kenze run clean.dq --set DAY=2026-07-14
```

An unknown key in a recipe produces a clear error, including a suggestion for the
most similar valid step.

---

## 8. The Python API

kenze can be used directly from Python, which is convenient inside notebooks and
scripts.

```python
import kenze

# Run a full pipeline in one streaming pass.
n = kenze.sift(
    "big.parquet", "clean.csv",
    keep=["id", "city", "amount"],
    filter="amount > 0",
    sample=50000,
)

# Run a recipe file.
kenze.run("clean.dq", variables={"DAY": "2026-07-14"})

# Run arbitrary SQL and get the rows back.
rows = kenze.sql("SELECT city, count(*) FROM 'big.parquet' GROUP BY 1")

# Inspect.
kenze.profile("big.parquet")
kenze.stats("big.parquet")
```

The keyword arguments accepted by `kenze.sift` are the same words used by the
commands and the recipe steps: `keep`, `drop`, `filter`, `bbox`, `types`,
`fillna`, `mask`, `rename`, `dedup`, `sample`, and `head`.

Other functions available on the `kenze` module include `join`, `diff`, `split`,
`partition`, `pivot`, `peek`, `check`, `validate`, `init`, and `connect` (which
returns a pre-configured DuckDB connection if you want to work with DuckDB directly).

### Hand off to a dataframe

Clean a file larger than memory, then pass the cleaned result straight to a fast
in-memory dataframe without a disk round-trip:

```python
import kenze
frame = kenze.to_polars("SELECT * FROM 'big.parquet' WHERE amount > 0")
table = kenze.to_arrow("SELECT city, count(*) FROM 'big.parquet' GROUP BY 1")
df    = kenze.to_df("SELECT * FROM 'big.parquet' LIMIT 1000")
```

These need the corresponding library, available as extras:
`pip install kenze[polars]`, `kenze[arrow]`, `kenze[pandas]`, or `kenze[all]`.

---

## 9. Working with cloud storage

kenze reads and writes cloud object storage directly, without downloading a file
first. Supported schemes include `s3://`, `gs://`, and Azure paths. The first
time a remote path is used, the required DuckDB extension is loaded
automatically.

```
kenze profile s3://bucket/huge.parquet
kenze filter  s3://bucket/huge.parquet --where "amount > 0" -o local.csv
```

### Credentials

Credentials are read from the standard AWS environment variables:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION` (or `AWS_REGION`)
- `AWS_SESSION_TOKEN` (optional, for temporary credentials)

If those variables are set, kenze configures DuckDB with them directly. If they
are not set, it falls back to the standard credential chain, which also reads
configuration files and instance roles.

### A note on performance

Reading a file's schema or row count from cloud storage reads only its metadata
and is effectively instant, even for very large files. Reading the actual row
data depends on the file's internal structure and on your network throughput; a
file written with very large internal row groups may transfer a large amount of
data even for a small number of rows. This is a property of the file and the
network, not of kenze.

---

## 10. Global options

These options apply to any command and may be given either before or after the
command name.

| Option | Effect |
| --- | --- |
| `--memory-limit GB` | Pin the memory budget to a fixed number of gigabytes, for reproducible runs, instead of auto-sizing from free RAM. |
| `--temp-dir DIR` | Use a specific directory for disk-spill. Point this at a drive with plenty of free space when processing very large files. |
| `--threads N` | Cap the number of CPU threads DuckDB uses (default: all cores). |
| `--no-disk-check` | Skip the pre-flight free-space check. |
| `--skip-bad-lines` | Ignore malformed rows in CSV input rather than stopping on them. |
| `--skip N` | Skip N preamble rows before the CSV header — comment banners, blank lines and other junk that messy exports put at the top. |
| `--no-history` | Do not record this run in the local run ledger (`~/.kenze/history.jsonl`). Recording can also be disabled globally with the environment variable `KENZE_NO_HISTORY=1`. |
| `--errors PATH` | Quarantine malformed CSV rows to a file (with line/column diagnostics) and keep processing the good rows. |
| `--append` | Append to an existing csv/json output instead of overwriting it. |
| `--source-format FMT` | Read a lakehouse table: `delta` or `iceberg` (the extension is loaded on demand; needs internet the first time). |
| `--dry-run` | Print the compiled query and the output schema without executing anything. Useful before a large or expensive run. |
| `--log PATH` | After a transform, write a JSON run manifest recording the inputs, output, row count, timing, and steps. |
| `-q`, `--quiet` | Suppress the summary line printed after a transform. |
| `--version` | Print the version and exit. |

The run manifest written by `--log` provides a lightweight audit trail: it
records exactly what a run did without requiring any external observability
system.

---

## 11. The memory model

The promise that kenze does not run out of memory rests on a specific
configuration of DuckDB, applied automatically to every connection.

**The memory ceiling is a fraction of free RAM.** By default the ceiling is set
to roughly sixty percent of the memory that is currently available, measured at
the moment the connection opens. It is deliberately based on free memory rather
than total memory so that a large job cannot claim everything on the machine and
be terminated by the operating system while other applications are running.

**Disk spill is enabled.** A temporary directory is configured so that when a job
genuinely needs more working space than the memory ceiling permits, DuckDB writes
intermediate data to disk rather than failing. This is the mechanism that allows
files larger than RAM to be processed successfully.

**Insertion order is not preserved.** This setting is a meaningful memory saving
on large writes and is enabled because a data-preparation tool rarely needs to
preserve the exact original row order through an aggregation or a large sort.

**All cores are used.** The thread count is set to the number of CPU cores so
that work is parallelised.

**Pinning the budget.** The automatic sizing is convenient but, because it
depends on how much memory happens to be free at the time, run times can vary
between an idle machine and a busy one. When predictable behaviour matters — for
example under a scheduled job with a time budget — set `--memory-limit` to a
fixed value. The job will then use exactly that budget and spill to disk beyond
it, giving consistent behaviour regardless of what else is running.

**A pre-flight disk check.** Before a large local write, kenze verifies that the
output drive and the spill directory have enough free space, and stops with a
clear message if they do not, rather than failing partway through a long
operation. This check can be disabled with `--no-disk-check`.

---

## 12. Supported formats

kenze reads and writes:

- CSV (`.csv`) and tab-separated values (`.tsv`)
- Parquet (`.parquet`, `.pq`)
- JSON and newline-delimited JSON (`.json`, `.ndjson`)
- Excel workbooks (`.xlsx`, `.xls`), read and written via DuckDB's `excel` extension
- GeoJSON (`.geojson`), read and written via DuckDB's `spatial` extension (see `convert`)
- Any of the above compressed with gzip (`.gz`), read and written transparently

The format of an operation is determined by file extension, both for reading and
for writing. `convert` exists specifically to change format by writing to a
different extension.

---

## 13. Where kenze stops, by design

kenze is one dependency and one machine. That is the entire point: it maximises
the use of a single computer's cores and disk so that one laptop or one virtual
machine can process files far larger than its memory. It does not, and will not,
do the following, because doing so would turn it into a different and much heavier
kind of tool:

- **Distributed execution.** It does not run a cluster or spread work across
  multiple machines. If you have genuinely outgrown a single machine — multi-
  terabyte workloads with cluster orchestration — a distributed engine such as
  Spark is the right tool. kenze is what you use before you reach that point.
- **Removing the disk-spill cost.** Spilling to disk is slower than working
  entirely in memory; that is an inherent trade-off of never failing on a large
  file. The memory-limit control and the disk pre-check mitigate the surprises,
  but disk is not memory.
- **Heavy data-lineage integration.** It records a lightweight run manifest with
  `--log`, but it does not integrate with enterprise lineage or observability
  platforms.

These boundaries are stated plainly so that the tool is adopted where it fits and
avoided where it does not.

---

## 14. Troubleshooting

**The `kenze` command is not found.** Installation succeeded but the executable's
directory is not on your PATH. Run `python -m kenze` as an immediate workaround,
or see section 3 for permanent fixes.

**A CSV fails to read because of malformed rows.** Run `kenze check <file>` to see
how many rows are affected, then re-run your command with `--skip-bad-lines` to
ignore them.

**A run stops with a free-space error before starting.** This is the pre-flight
disk check. Free up space, point `--temp-dir` at a drive with more room, or pass
`--no-disk-check` to proceed anyway.

**Run times vary between machines or times of day.** The automatic memory sizing
depends on free RAM. Use `--memory-limit` to pin the budget for consistent
behaviour.

**A negative bounding box is rejected as an unknown option.** Attach it with an
equals sign so the shell does not interpret it as a flag: `--bbox=-10,35,5,45`.

---

## 15. Versioning and releases

kenze follows semantic versioning. The core stays small and grows one release at
a time. Each release is built, checked, published to PyPI, and verified with a
clean-environment install before being considered done.

The current release is 0.9.0.

---

## 16. Roadmap

The following items are intentionally deferred. They are larger, independent
pieces of work rather than gaps in the current tool.

- **Single-binary distribution.** A self-contained executable that can be
  installed without a Python environment, for locked-down production servers.
- **A browser playground.** A page where a file can be dropped and a recipe
  written and previewed entirely locally, compiled to WebAssembly, so that the
  tool can be tried without installing anything.

The following are deliberately excluded from the core to preserve its simplicity
and small dependency surface, and would only ever be optional extensions:
inline Python user-defined functions, embedding generation, and text chunking
for retrieval pipelines.

---

## 17. License

Released under the MIT License.
