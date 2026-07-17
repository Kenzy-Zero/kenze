# kenze

[![PyPI version](https://img.shields.io/pypi/v/kenze.svg)](https://pypi.org/project/kenze/)
[![Python versions](https://img.shields.io/pypi/pyversions/kenze.svg)](https://pypi.org/project/kenze/)
[![License](https://img.shields.io/pypi/l/kenze.svg)](https://github.com/Kenzy-Zero/kenze/blob/main/LICENSE)
[![Downloads](https://static.pepy.tech/badge/kenze)](https://pepy.tech/project/kenze)
[![CI](https://github.com/Kenzy-Zero/kenze/actions/workflows/ci.yml/badge.svg)](https://github.com/Kenzy-Zero/kenze/actions/workflows/ci.yml)

**Big-file data prep that never runs out of memory — an interactive shell *and* a one-line CLI.**

`kenze` cleans and reshapes data files (CSV, Parquet, JSON) that are too big for
pandas. It's a friendly front-end over [DuckDB](https://duckdb.org): DuckDB does
the heavy lifting (streaming, disk-spill, all your CPU cores), `kenze` makes it
effortless — and auto-configures memory so your job doesn't crash.

![kenze in action — load, filter, plot and run a 60M-row file without ever running out of memory](https://raw.githubusercontent.com/Kenzy-Zero/kenze/main/demo.gif)

```bash
pip install kenze
```

One name for everything: `pip install kenze` → the `kenze` command → `import kenze`.

## The interactive shell

Just run `kenze`. You land in a live session: load a file once, stack simple
steps (each **previews as you go**), then run the pipeline to a file or save it
as a reusable recipe. Type `/` for a live command menu; **TAB** autocompletes
your file's real column names.

```
kenze > load sales.parquet          # 60M rows, opens instantly
kenze > filter amount > 0           # each step previews live
kenze > plot amount --by city       # ascii bar chart of the live data
kenze > keep id, city, amount
kenze > dedup id
kenze > assert-unique id            # a data-quality guard, checked before writing
kenze > run clean.csv               # streamed through DuckDB, no OOM
```

It never loads more than it needs, so counts and previews on a 60-million-row file
come back in well under a second, and full writes stream through DuckDB with a
progress bar. Everything the CLI can do is in the shell — see **[SHELL.md](https://github.com/Kenzy-Zero/kenze/blob/main/SHELL.md)**.

## Feature highlights

- **An interactive shell** (`kenze`) with a `/` command menu, live previews, schema-aware autocomplete, and data-quality guards — plus the same as a one-line CLI for scripts and cron.
- **Process files bigger than your RAM** without crashing — memory is auto-capped and DuckDB spills to disk.
- **38 CLI commands** for the everyday work: `keep`, `drop`, `filter`, `rename`, `cast`, `fillna`, `dedup`, `sample`, `join`, `diff`, `pivot`, `split`, `partition`, and more — no SQL needed.
- **Model-ready in one step** — `scale`, `bin`, `encode`, `onehot`, `clip-outliers`, and a reproducible `traintest` split turn a clean file into a model-ready dataset you hand straight to scikit-learn / XGBoost.
- **See your data** — `plot amount --by city` draws an ASCII bar chart or histogram right in the terminal, so you spot skew and dirty data instantly.
- **Excel in and out** — read and write `.xlsx` workbooks natively (`convert big.parquet -o report.xlsx`), no extra dependency.
- **Messy CSVs, handled** — `--skip N` drops junk preamble rows; the shell even auto-detects and skips them for you.
- **Readable recipes** (`.dq` files) that chain steps into one streaming pass, with `${VAR}` templating for scheduled jobs.
- **Read and write the cloud directly** — `s3://`, `gs://`, `https://` — nothing to download first.
- **A run ledger** — `history` shows your recent runs (input → output, rows, time).
- **Data-quality guards** (`assert`, `assert_unique`, `assert_not_null`), **PII masking** (`mask`), **schema validation** (`validate`) — a failed check aborts before anything is written.
- **No lock-in** — `eject` any recipe to raw DuckDB SQL or Python.
- **Use it from Python too** — `import kenze` and call `kenze.sift(...)`, `kenze.sql(...)`.
- Atomic writes and clean, cross-platform output on any terminal.

## Why

- **It doesn't OOM.** Memory is capped to a fraction of *free* RAM and DuckDB
  spills to disk instead of dying. Point it at a file bigger than your RAM; it's fine.
- **No SQL, no pandas.** Simple verbs, or a readable recipe file.
- **One streaming pass.** A whole recipe compiles to a single query — no
  intermediate files, so it's fast and light.
- **Any format, local or cloud.** CSV / Parquet / JSON, plain or `.gz`,
  on disk or on `s3://` / `gs://` / `https://` — auto-detected.

## One-liners

```bash
kenze profile  sales.parquet                          # schema + row count, instantly
kenze peek     sales.parquet                           # first rows + types + null counts
kenze stats    sales.parquet                           # per-column min/max/nulls/unique
kenze plot     sales.parquet amount --by city          # ascii bar chart in the terminal
kenze plot     sales.parquet amount                    # ascii histogram of a numeric column
kenze check    sales.csv                               # is the file valid? any bad rows?

kenze keep     sales.parquet --cols id,city,amount -o small.csv
kenze drop     users.csv     --cols email,phone    -o clean.parquet
kenze filter   sales.parquet --where "amount > 100" -o big.csv
kenze rename   sales.csv     --map "amount:total"   -o out.csv
kenze cast     users.csv     --types "zip:VARCHAR"  -o out.parquet   # keep leading zeros
kenze fillna   users.csv     --with "city:Unknown"  -o out.csv
kenze mask     users.csv     --cols email,ssn --method hash -o safe.csv
kenze dedup    users.csv     --on id               -o unique.parquet
kenze sample   sales.parquet --n 50000             -o sample.csv
kenze clip     points.parquet --bbox -10,35,5,45    -o region.parquet

kenze join     orders.csv users.parquet --on user_id -o joined.parquet
kenze diff     old.csv new.csv --on id                # added / removed / changed
kenze pivot    sales.csv --on city --values amount --agg sum --group region -o wide.csv
kenze unpivot  wide.csv  --cols jan,feb,mar --name month --value sales -o long.csv
kenze filter   "sales_*.csv" --where "amount>0" -o all.csv   # globs unify schemas
kenze split    sales.parquet --by city -o by_city/    # one file per value
kenze partition sales.parquet --by year -o lake/      # hive year=2026/ folders
kenze convert  sales.parquet -o report.xlsx          # write a real Excel workbook
kenze keep     messy.csv --cols id,amount --skip 3 -o clean.csv  # drop junk preamble

kenze sql  "SELECT *, lag(amount) OVER (ORDER BY ts) FROM 'sales.parquet'" -o out.csv
kenze history                                         # your recent runs
```

Read or write the cloud directly (nothing to download first):

```bash
kenze filter s3://bucket/huge.parquet --where "amount > 0" -o local.csv
```

Pipe like any Unix tool (use `-` for stdin/stdout):

```bash
cat data.csv | kenze filter - --where "x > 1" -o - | gzip > out.csv.gz
```

## Recipes

Chain steps in a readable `.dq` file — they run as one streaming pass:

```yaml
# clean.dq
input:  data/sales_${DAY}.parquet     # ${DAY} filled from --set or the environment
keep:   [id, city, amount]
types:  zip:VARCHAR
filter: amount > 0
fillna: city:Unknown
dedup:  id
sample: 50000
output: out/clean.csv
```

```bash
kenze run clean.dq --set DAY=2026-07-14
kenze recipe                 # show every valid recipe step
kenze eject clean.dq --to sql    # print the raw DuckDB SQL (no lock-in)
```

Bake **data-quality tests** right into a recipe — they run before anything is written,
so a failed check aborts with no output:

```yaml
assert:          row_count > 0
assert_unique:   id
assert_not_null: id, email
```

## From Python

```python
import kenze
kenze.sift("big.parquet", "clean.csv", keep=["id", "city"], filter="amount > 0", sample=50000)
rows = kenze.sql("SELECT city, count(*) FROM 'big.parquet' GROUP BY 1")
kenze.profile("big.parquet")
```

## Handy flags

- `--dry-run` — show the compiled query + output schema *without* running it.
- `--errors bad.csv` — quarantine malformed CSV rows to a file (with line/column diagnostics) and keep going.
- `--append` — add to an existing csv/json output instead of overwriting.
- `--source-format delta|iceberg` — read a Delta Lake or Apache Iceberg table.
- `--memory-limit 8` — pin the RAM budget (GB) for reproducible / SLA runs (great for shared CI/Airflow nodes).
- `--temp-dir D:/spill` — put disk-spill where there's room.
- `--threads N` — cap how many CPU threads DuckDB uses.
- `--skip-bad-lines` — ignore malformed rows in a dirty CSV.
- `--skip N` — skip N preamble rows before the CSV header (comment banners, blank lines).
- `--log run.json` — write a run manifest (inputs, rows, timing).
- `--no-history` — don't record this run in `~/.kenze/history.jsonl`.
- Writes are **atomic** — a cancelled run never leaves a half-written file.

## Hand off to a dataframe

Clean a huge file, then pass the result straight to Polars / Arrow / pandas — no disk round-trip:

```python
import kenze
df = kenze.to_polars("SELECT * FROM 'big.parquet' WHERE amount > 0")   # pip install kenze[polars]
tbl = kenze.to_arrow("SELECT city, count(*) FROM 'big.parquet' GROUP BY 1")   # kenze[arrow]
```

## Commands

`profile` · `peek` · `stats` · `plot` · `check` · `validate` · `keep` · `drop` · `rename` · `cast` ·
`fillna` · `mask` · `scale` · `bin` · `encode` · `onehot` · `clip-outliers` · `filter` · `dedup` ·
`sample` · `head` · `clip` · `convert` · `join` · `diff` · `pivot` · `unpivot` · `split` ·
`partition` · `traintest` · `sql` · `eject` · `init` · `run` · `recipe` · `history`

Run any of these as a one-liner, or run `kenze` and do it all interactively — the
shell wraps every command above plus session helpers (`open`, `set`, `dryrun`,
`pwd`/`cd`, `undo`, `steps`). See **[SHELL.md](https://github.com/Kenzy-Zero/kenze/blob/main/SHELL.md)** for the shell guide.

## Performance

The whole point of kenze is that it doesn't fall over on files bigger than your
RAM. The repo ships a **reproducible benchmark** that proves it: it generates a
large synthetic CSV and runs the same job (filter → group-by → aggregate) with
pandas, polars and kenze, each given the **same memory budget**.

- **pandas** (eager) tries to load the whole file, blows past the budget, and dies with an out-of-memory error.
- **kenze** streams the job *within* the budget — spilling to disk when it has to — and finishes.

Run it yourself:

```bash
pip install pandas polars psutil
python bench/benchmark.py --rows 60000000 --mem-gb 3
```

It prints a markdown table (outcome / wall time / peak memory) and writes
`bench/RESULTS.md`. The same benchmark runs in CI
([Benchmark workflow](https://github.com/Kenzy-Zero/kenze/actions/workflows/benchmark.yml)),
where the results are uploaded as a build artifact and posted to the run summary.

## Where it stops (on purpose)

kenze is one dependency and one machine — that's the whole point. It maxes out
your cores and spills to disk so a single laptop or VM can chew through files far
bigger than its RAM. It does **not** run a cluster. If you've genuinely outgrown
one machine (multi-terabyte, distributed pipelines with SLAs and lineage
tracking), reach for Spark/Dask — kenze is the tool you use *before* you need those.

## Troubleshooting

**`'kenze' is not recognized` / `kenze: command not found`?**
`pip` installed kenze correctly — the command just landed in a folder that isn't on
your PATH (this affects every pip-installed CLI). Options:

- **Use it now, no setup:** `python -m kenze --help`
- **Fix it for good:** reinstall Python from [python.org](https://www.python.org/downloads/)
  with **"Add python.exe to PATH"** ticked, or use `python -m pipx install kenze`.

## Feedback, bugs & feature requests

Found a bug, want a new command, or hit something confusing? **Open an issue:**
[github.com/Kenzy-Zero/kenze/issues](https://github.com/Kenzy-Zero/kenze/issues).
(The shell prints this link too — `help`.) Pull requests welcome — see
**[CONTRIBUTING.md](https://github.com/Kenzy-Zero/kenze/blob/main/CONTRIBUTING.md)**.
A [GitHub star](https://github.com/Kenzy-Zero/kenze) helps others find kenze.

Every command is covered by a test suite (`tests/`) that runs on Linux and Windows
across Python 3.9–3.13 (see the CI badge) — including the data-quality guards and
the ML-prep transforms. Run it locally with `pip install -e ".[dev]" && pytest`.

MIT licensed.
