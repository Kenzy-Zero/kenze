# kenze — Python API reference

Everything the `kenze` command does, you can do from Python: `import kenze`.
Same engine, same never-OOM behaviour — you just call functions instead of typing
commands. This page documents every public function with its **exact signature**,
what each argument does, what it returns, and a runnable example.

```python
import kenze
print(kenze.__version__)
```

There are two ways to use the library:

1. **Whole-file, one call** — `kenze.sift(...)` runs a full clean-up in a single
   streaming pass. This is the everyday entry point.
2. **Building blocks** — the individual functions (`profile`, `count`, `join`,
   `to_polars`, …) for when you want one operation at a time.

Every function that touches data accepts an optional `con=` (a DuckDB connection
from `kenze.connect()`). Pass one to reuse the same tuned connection across many
calls; omit it and kenze opens and closes a fresh one for you.

---

## Contents

- [The whole-file entry point](#the-whole-file-entry-point) — `sift`, `run`, `sql`
- [The engine](#the-engine) — `connect`
- [Inspecting data](#inspecting-data) — `profile`, `peek`, `stats`, `count`, `check`, `validate`, `scaffold_schema`, `plot`, `history`
- [Transform and write](#transform-and-write) — `run_spec`, `build_query`, `run_sql`
- [Combine, reshape, split](#combine-reshape-split) — `join`, `diff`, `pivot`, `unpivot`, `split`, `partition`, `traintest`
- [Hand off to a dataframe](#hand-off-to-a-dataframe) — `to_polars`, `to_arrow`, `to_df`
- [Scaffolding](#scaffolding) — `init`
- [Reports](#reports) — `kenze.report.report`
- [The spec dictionary](#the-spec-dictionary) — every step key for `sift` / `run_spec`

---

## The whole-file entry point

### `sift(input, output, con=None, quiet=True, **steps)`

Run one streaming pass: read `input`, apply the `steps`, write `output`. The whole
recipe compiles to a single DuckDB query (no intermediate temp files), and memory
is auto-capped so it never OOMs. Returns the number of rows written (`int`).

| argument | meaning |
|---|---|
| `input` | path to read: `.csv` / `.parquet` / `.json` / `.gz` / `.xlsx` / `.geojson`, or `s3://` / `gs://` / `https://`. A glob like `sales_*.csv` unions files by name. |
| `output` | path to write; format is taken from its extension. `-` writes to stdout. |
| `con` | reuse a `kenze.connect()` connection (optional). |
| `quiet` | `True` (default) suppresses the summary line. |
| `**steps` | any of the [spec keys](#the-spec-dictionary): `keep`, `drop`, `filter`, `bbox`, `types`, `fillna`, `mask`, `rename`, `scale`, `bin`, `encode`, `onehot`, `clip_outliers`, `dedup`, `sample`, `sort`, `head`. |

```python
import kenze
n = kenze.sift(
    "big.parquet", "clean.csv",
    keep=["id", "city", "amount"],
    filter="amount > 0",
    dedup="id",
    sort="amount:desc",
    head=100,          # sort + head = top 100
)
print(n, "rows written")
```

### `run(recipe_path, variables=None, con=None, quiet=True)`

Run a `.dq` recipe file (the same format as `kenze run`). `variables` fills any
`${VAR}` placeholders in the recipe. Returns rows written (`int`).

```python
kenze.run("clean.dq", variables={"CUTOFF": "100"})
```

### `sql(query, con=None)`

Run any DuckDB SQL and get the rows back as a list of tuples. Reference files
inline. This is the escape hatch for anything the verbs don't cover.

```python
rows = kenze.sql("SELECT city, count(*) FROM 'big.parquet' GROUP BY 1 ORDER BY 2 DESC")
```

---

## The engine

### `connect(mem_fraction=0.6, threads=None, temp_dir=None, memory_limit_gb=None, progress=False)`

Open a tuned DuckDB connection. You rarely call this directly — every function
opens one automatically — but if you make many calls, create one and pass it as
`con=` to avoid re-tuning each time. Returns a `duckdb.DuckDBPyConnection`.

| argument | meaning |
|---|---|
| `mem_fraction` | fraction of **free** RAM to use as the ceiling (default `0.6`). |
| `threads` | max threads (default: all cores). |
| `temp_dir` | directory for disk-spill (default: a `kenze_spill` folder in the system temp). |
| `memory_limit_gb` | pin the RAM budget in GB for reproducible runs (overrides `mem_fraction`). |
| `progress` | show DuckDB's progress bar. |

```python
con = kenze.connect(memory_limit_gb=4)
kenze.profile("big.parquet", con=con)
kenze.count("big.parquet", "city", con=con)
con.close()
```

---

## Inspecting data

These print a formatted result and/or return a value; none require an output file.

They all accept the same three arguments for a messy CSV, and each does a
different job:

| argument | what it does |
|---|---|
| `skip=N` | drop N preamble rows before the header — comment banners and other junk at the top of an export. |
| `skip_bad=True` | ignore rows the parser rejects. The row is **dropped**, not repaired. |
| `strict=False` | read a file that breaks the CSV standard outright — mixed line endings, a stray quote in an unquoted field, which is ordinary Spark output. Distinct from `skip_bad`: this **accepts** a non-conforming row and discards any fields past the header, so it is the flag for a file that will not open at all. |

### `profile(path, con=None, fmt=None, skip=0, skip_bad=False, strict=True) -> int`

Print the schema and exact row count. For Parquet this reads only metadata, so
it's instant on huge files. Returns the row count. `fmt` reads a lakehouse table
(`"delta"` / `"iceberg"`); `skip` drops N preamble rows before a CSV header.

### `peek(path, n=20, con=None, fmt=None, skip=0, skip_bad=False, strict=True)`

Print the first `n` rows with types and null counts.

### `stats(path, con=None, fmt=None, skip=0, skip_bad=False, strict=True)`

Print a per-column summary: min / max / null% / approx-unique.

### `count(path, by, out=None, distinct=None, top=None, con=None, quiet=False, fmt=None, skip=0, disk_check=True, skip_bad=False, strict=True)`

Value-counts / GROUP BY count — how many rows per value(s) of a column, biggest
first. Prints if `out` is omitted, writes a file if `out` is given. Returns the
number of groups.

| argument | meaning |
|---|---|
| `by` | column, or list of columns, to group by. |
| `out` | write the counts to a file (omit to print). |
| `top` | keep only the top N groups. |
| `distinct` | count **unique** values of this column per group (e.g. unique users per city) instead of rows. |

```python
kenze.count("sales.csv", "city")                          # print value-counts
kenze.count("sales.csv", "city", top=10, out="top.csv")   # top 10 -> file
kenze.count("sales.csv", "city", distinct="user_id")      # unique users per city
kenze.count("sales.csv", ["city", "category"])            # group by two columns
```

### `check(path, con=None, skip=0) -> int`

Pre-flight integrity scan: is the file readable, how many rows are malformed.
Returns a non-zero code on problems.

### `validate(path, schema_path, con=None, skip=0, skip_bad=False, strict=True) -> int`

Check a file against a target schema JSON. Returns the number of problems, so
`0` means the file conforms. Reports every column whose type does not match,
every required column that is absent, and any nulls in columns listed under
`not_null`.

### `scaffold_schema(path, out, con=None, skip=0, skip_bad=False, strict=True) -> str`

Write the schema JSON that describes `path` as it is today, so you do not have
to write one by hand. Every column is recorded with its real type, and every
column with **no nulls right now** is listed under `not_null` — a measured fact
about this file, meant as a starting point to edit rather than a claim about
what the data means. Returns the path written.

```python
kenze.scaffold_schema("sales.csv", "schema.json")   # write the contract
kenze.validate("next_month.csv", "schema.json")     # 0 = still conforms
```

### `plot(path, column, by=None, agg=None, bins=20, top=20, width=48, con=None, fmt=None, skip=0, skip_bad=False, strict=True)`

Print an ASCII chart of a column: a value-counts / bar chart (text column), a
histogram (numeric), or an aggregate per category with `by=`.

```python
kenze.plot("sales.csv", "city")                    # value-counts bar chart
kenze.plot("sales.csv", "amount")                  # histogram
kenze.plot("sales.csv", "amount", by="city", agg="sum")   # sum(amount) per city
```

### `history(n=20, con=None) -> int`

Print your recent kenze runs (input → output, rows, time) from `~/.kenze/history.jsonl`.

---

## Transform and write

### `run_spec(spec, con=None, quiet=False, disk_check=True, log=None, dry_run=False, action=None)`

The engine under `sift`. Takes a full [spec dictionary](#the-spec-dictionary)
(including `input` and `output`) and runs it. `dry_run=True` prints the compiled
query + output schema without writing; `log="run.json"` writes a run manifest.

```python
kenze.run_spec({
    "input": "big.parquet", "output": "clean.csv",
    "filter": "amount > 0", "sort": "amount:desc", "head": 100,
})
```

### `build_query(con, spec) -> str`

Return the exact DuckDB SQL a spec compiles to, without running it. Useful for
inspection, testing, or handing the SQL somewhere else (this is what `eject` uses).

```python
con = kenze.connect()
print(kenze.build_query(con, {"input": "big.parquet", "filter": "amount > 0"}))
```

### `run_sql(query, out=None, con=None, quiet=False, disk_check=True)`

Run SQL and either **print** the result (no `out`) or **write** it atomically to a
file (`out=`). Like `kenze.sql` but with file output and the safe-write machinery.

```python
kenze.run_sql("SELECT city, count(*) c FROM 'big.parquet' GROUP BY 1", out="counts.csv")
```

---

## Combine, reshape, split

### `join(left, right, on, how="inner", out=None, con=None, quiet=False, disk_check=True)`

Join two files on a key. `on` is a key column (or list); `how` is
`inner` / `left` / `right` / `full`.

```python
kenze.join("orders.csv", "users.parquet", on="user_id", how="left", out="joined.parquet")
```

### `diff(old, new, on, out=None, con=None)`

Compare two datasets on a key — reports added / removed / changed rows. `out`
optionally writes the changed keys.

### `pivot(input_path, on, values, agg="sum", group=None, out=None, con=None, quiet=False, disk_check=True)`

Reshape long → wide: distinct values of `on` become columns, aggregating `values`
with `agg`. `group` keeps a row-identity column.

```python
kenze.pivot("sales.csv", on="month", values="amount", agg="sum", group="region", out="wide.csv")
```

### `unpivot(input_path, cols, name="name", value="value", out=None, con=None, quiet=False, disk_check=True)`

Reshape wide → long: fold `cols` into two columns (`name`, `value`).

```python
kenze.unpivot("wide.csv", cols=["jan", "feb", "mar"], name="month", value="sales", out="long.csv")
```

### `split(input_path, by, out_dir, fmt="csv", con=None, max_groups=2000)`

Write one file per distinct value of column `by` into `out_dir`. `max_groups`
guards against accidentally exploding into thousands of files.

```python
kenze.split("sales.parquet", by="city", out_dir="by_city/", fmt="parquet")
```

### `partition(input_path, by, out_dir, fmt="parquet", con=None, quiet=False)`

Hive-style partitioned output — `col=value/` folders.

```python
kenze.partition("sales.parquet", by="year", out_dir="lake/")
```

### `traintest(input_path, out_dir, ratio=0.8, seed=42, by=None, before=None, fmt="parquet", con=None, quiet=False)`

Split into `train` + `test` files. Random by default (`ratio`, `seed` — reproducible),
or leak-free time-based with `by=` (a time column) and `before=` (rows before the
cutoff → train).

```python
kenze.traintest("features.parquet", out_dir="split/", ratio=0.8, seed=42)
kenze.traintest("events.parquet", out_dir="split/", by="ts", before="2026-01-01")
```

---

## Hand off to a dataframe

Prep the big file with kenze (never-OOM), then hand a *manageable* result to a
fast in-memory dataframe. Each needs its optional extra:
`pip install "kenze[polars]"` / `"[arrow]"` / `"[pandas]"` (or `"[all]"`).

### `to_polars(query, con=None)` · `to_arrow(query, con=None)` · `to_df(query, con=None)`

Run a query and return a Polars DataFrame / Arrow Table / pandas DataFrame.

```python
df = kenze.to_polars("SELECT * FROM 'big.parquet' WHERE amount > 0")   # kenze[polars]
tbl = kenze.to_arrow("SELECT city, sum(amount) FROM 'big.parquet' GROUP BY 1")  # kenze[arrow]
pdf = kenze.to_df("SELECT * FROM 'big.parquet' LIMIT 100000")          # kenze[pandas]
```

---

## Scaffolding

### `init(path="recipe.dq", input_path=None, con=None)`

Write a starter `.dq` recipe. Give `input_path` and its columns are read and
pre-filled, so you just delete what you don't want.

```python
kenze.init("clean.dq", input_path="sales.csv")
```

---

## Reports

Turning a data file into a styled PDF/HTML report lives in `kenze.report`
(needs `pip install "kenze[report]"`). See **[report.md](report.md)** for the full guide.

```python
from kenze.report import report
report("summary.csv", output="out.pdf", variables={"title": "Q1 Review", "currency": "$"})
```

---

## The spec dictionary

`sift(**steps)` and `run_spec(spec)` both take the same keys. Use only the ones you
need, in any order — they compile into one streaming query.

| key | value | does |
|---|---|---|
| `input` | path | (spec only) file to read |
| `output` | path | (spec only) where to write |
| `keep` | `["id", "city"]` or `"id, city"` | keep only these columns |
| `drop` | `["notes"]` | remove these columns |
| `filter` | `"amount > 0"` | keep rows matching a SQL condition |
| `bbox` | `"minlon,minlat,maxlon,maxlat"` | keep rows inside a lat/lon box |
| `types` | `"zip:VARCHAR, id:VARCHAR"` | cast columns (stops leading-zero loss) |
| `fillna` | `"city:Unknown, score:0"` | replace nulls |
| `mask` | `"email, ssn"` | mask sensitive columns (`mask_method`: `hash`/`redact`/`null`) |
| `rename` | `"old:new, amount:total"` | rename columns |
| `scale` | `"amount:minmax, age:zscore"` | scale numeric columns for ML |
| `bin` | `"age:5, income:4:quantile"` | bucket a numeric column into N bins |
| `encode` | `"city, level"` | label-encode categories to ints |
| `onehot` | `"city, brand:20"` | one-hot encode (top-N + `_other`) |
| `clip_outliers` | `"amount:iqr, age:pct"` | winsorize extreme values |
| `dedup` | `"id"` or `"all"` | drop duplicate rows |
| `sample` | `50000` | keep N random rows |
| `sort` | `"revenue:desc, name"` | order rows (add `:desc` per column) |
| `head` | `100` | keep the first N rows (after `sort` = top N) |
| `assert` | `"row_count > 0"` | fail the run unless this holds (may be a list) |
| `assert_unique` | `"id"` | fail if duplicates (may be a list) |
| `assert_not_null` | `"id, email"` | fail if nulls (may be a list) |

---

See also: **[CLI reference](../DOCS.md)** · **[interactive shell](../SHELL.md)** · **[reports](report.md)**.
