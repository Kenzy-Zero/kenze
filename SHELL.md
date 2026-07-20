# The kenze shell

An interactive session for wrangling data files, in the spirit of a modern REPL:
you load a file once, stack simple steps (each previews live), then run the
pipeline to an output file or save it as a reusable recipe.

If you have used the one-line CLI (`kenze filter big.csv -o clean.csv`), the shell
is the same engine with a conversational front-end. Nothing is different under the
hood: the never-out-of-memory DuckDB engine, all formats (csv / parquet / json /
gzip), and the same steps.

---

## Install and launch

Nothing extra to install - the shell ships with kenze:

    pip install kenze

Launch it by running kenze with no arguments, or with the `shell` subcommand:

    kenze
    kenze shell

You land at a `kenze >` prompt. Type `help` for the command list, or `/` for the
live menu. Leave with `exit` (or Ctrl-D).

On a terminal that cannot be driven for a rich UI (some minimal shells like
git-bash/mintty), the session still runs as a plain line-based loop - just without
colours and the `/` menu.

---

## The mental model

Think of it as stacking blocks. Each command you run is one **step** added on top
of the last, and the shell shows you a short preview after every step. When you
like the stack, you `run` it to a file or `save` it as a recipe.

    kenze > load sales.parquet          load a file (once)
    kenze > filter amount > 0           step 1  (previews)
    kenze > keep id, city, amount       step 2  (previews)
    kenze > dedup id                    step 3  (previews)
    kenze > steps                       see the recipe so far
    kenze > run clean.csv               write the result

Steps are just a recipe being built live. `undo` removes the last step, `reset`
clears them all (the file stays loaded), and loading a new file starts fresh.

---

## Commands

### Look at data
| command | what it does |
|---|---|
| `load <file>` | load a data file (csv / parquet / json / gzip / **xlsx** / `s3://...`). `load messy.csv skip 3` drops preamble rows; obvious junk is auto-skipped for you |
| `open <recipe.dq>` | open a saved recipe into the session to view, tweak (`undo` / add steps) and run |
| `peek [n]` | preview the first rows (default 10) of the current pipeline |
| `schema` | the current columns and their types |
| `count` | how many rows the current pipeline produces |
| `stats` | per-column summary: min / max / nulls / approx-unique |
| `plot <col> [by <cat>]` | an ascii chart of the **live pipeline**: `plot amount` (histogram / value-counts), or `plot amount by city` / `plot amount city` (bar chart of an aggregate per category). Options: `agg sum\|count\|avg\|...`, `bins N`, `top N` |
| `check [file]` | integrity scan: readable? how many malformed rows? |
| `validate <schema.json> [file]` | check the file against a target schema |

### Shape it (each adds a step)
| command | example | what it does |
|---|---|---|
| `filter <condition>` | `filter amount > 0` | keep rows matching a SQL condition |
| `keep <cols>` | `keep id, city` | keep only these columns |
| `drop <cols>` | `drop notes, temp` | remove these columns |
| `rename <old:new>` | `rename amount:total` | rename a column |
| `cast <col:TYPE>` | `cast zip:VARCHAR` | change a column's type (e.g. keep leading zeros) |
| `fillna <col:value>` | `fillna city:Unknown` | replace nulls in a column |
| `mask <cols>` | `mask email, ssn` | one-way hash sensitive columns |
| `scale <col> [minmax\|zscore]` | `scale amount minmax` | scale a numeric column for ML |
| `bin <col> [N] [uniform\|quantile]` | `bin age 5` | bucket a numeric column into N bins (adds `col_bin`) |
| `encode <col>` | `encode city` | label-encode a category to 0-based integers |
| `onehot <col> [N]` | `onehot city 20` | one-hot encode to 0/1 columns (top-N + `_other`) |
| `clip-outliers <col> [iqr\|pct]` | `clip-outliers amount iqr` | cap extreme values (winsorize) |
| `dedup [cols]` | `dedup id` | drop duplicate rows (a column, or `dedup` for whole-row) |
| `clip <bbox>` | `clip 54,24,56,26` | keep rows inside a lon/lat box (min_lon,min_lat,max_lon,max_lat) |
| `sample <n>` | `sample 1000` | keep N random rows |
| `head <n>` | `head 100` | keep the first N rows |

### Combine, reshape and split (operate on the loaded file)
These run immediately and write their own output. They use the loaded file - if you
have pending pipeline steps, run or save them first to apply them.

| command | example | what it does |
|---|---|---|
| `join <right> <key> <out> [how]` | `join orders.csv id joined.csv left` | join the loaded file with another on a key (inner/left/right/full) |
| `diff <other> <key> [out]` | `diff yesterday.csv id` | added / removed / changed vs another snapshot (same schema); optional out writes the changed keys |
| `pivot <on> <values> <out> [agg]` | `pivot month sales wide.csv sum` | reshape long to wide |
| `unpivot <cols> <out>` | `unpivot jan,feb,mar long.csv` | reshape wide to long |
| `split <by> <dir> [fmt]` | `split city cities/` | one file per distinct value of a column |
| `partition <by> <dir> [fmt]` | `partition year,month data/` | hive-style `col=value/` folders |
| `traintest <dir> [ratio R] [seed N] [by <col> before <val>]` | `traintest splits/ ratio 0.8` | split into train/test files (random or time-based) |

### Data-quality guards
Declare checks that run **before** anything is written - if a check fails, `run`
aborts and no output file is produced. Saved into the recipe by `save`.

| command | example | what it does |
|---|---|---|
| `assert <condition>` | `assert row_count > 0` | fail unless the condition holds (use `row_count`) |
| `assert-unique <cols>` | `assert-unique id` | fail if these columns have duplicates |
| `assert-not-null <cols>` | `assert-not-null id, email` | fail if these columns contain nulls |

### The pipeline
| command | what it does |
|---|---|
| `steps` | show the recipe (and guards) built so far |
| `undo` | remove the last step |
| `reset` | clear all steps (keep the loaded file) |

### Get it out
| command | what it does |
|---|---|
| `run <name> [append] [errors <file>] [log <file>]` | run the pipeline and write the result (format from the extension). `append` adds to an existing file, `errors` quarantines bad CSV rows, `log` writes a JSON run manifest |
| `save <name.dq>` | save the pipeline as a reusable recipe file |
| `dryrun` | show what `run` would write (the output columns) without writing |
| `eject [python] [<file>]` | print the pipeline's DuckDB SQL (or Python); add a filename (`eject out.sql` / `eject out.py`) to save it - no lock-in |
| `sql <query>` | run any DuckDB SQL and print the result (window functions, group-by, ...) |

### The shell
| command | what it does |
|---|---|
| `pwd` | show the output folder (where `run` / `save` write) |
| `cd <dir>` | change the output folder |
| `set` | show / change session settings (see below) |
| `history [n]` | your recent runs (input -> output, rows, time), from `~/.kenze/history.jsonl` |
| `recipe` | show the `.dq` recipe format reference |
| `help` | the guided command list |
| `clear` | clear the screen |
| `exit` | leave the shell |

`set` mirrors the CLI's power flags for the session: `set memory <GB>` (or `auto`)
pins the RAM budget, `set threads <N>` caps cores, `set skip-bad on` ignores
malformed CSV rows, `set temp <dir>` moves disk-spill, `set disk-check off` skips
the pre-flight free-space check. To read a lakehouse table, `load <path> as delta`
(or `as iceberg`).

---

## Writing filters (read this once)

A filter condition is plain SQL, so two rules trip people up:

1. **Text values need single quotes**, and the match is exact / case-sensitive:

       filter city = 'London'         correct
       filter city = 'london'         finds nothing if the data says "London"
       filter city = London           error: "London" is read as a column name
       filter city = "London"         error: double quotes mean a column in SQL

2. **Numbers need no quotes**, and you can combine conditions:

       filter age > 30
       filter amount >= 100
       filter status = 'active' and amount > 0

If you type a simple, non-SQL condition like `filter status active` or
`filter city = london`, the shell tries to **auto-repair** it to valid SQL
(`status = 'active'`) and tells you how it read it — so a natural attempt still
works. It only steps in when the condition would otherwise error, and never
touches real SQL. Text matches are exact and case-sensitive, so `london` won't
match `London`.

Not sure how a value is spelled? Run `peek` or `stats` first to see the real
values. Every filter also runs as its own step, so you can stack several — filter
a few times, then `plot` or `run` charts/writes only the rows that survive.

---

## Where files go

`run` and `save` write to the **current output folder** - by default, the folder
you launched kenze from. The shell always prints the **full path** so it is never
a mystery:

    kenze > run clean.csv
      done: 53,557 rows -> C:\Users\you\clean.csv

To control the location, either give a full path, or set the folder once:

    kenze > pwd                        show the current output folder
    kenze > cd C:\Users\you\exports    change it
    kenze > run clean.parquet          now writes into that folder

Sub-folders in a path are created automatically (`run reports/2026/clean.csv`
just works).

---

## Autocomplete and keys

- Type `/` to open the command menu; keep typing to filter it (`/fi` -> filter).
- After `load`, typing a column argument suggests the file's real column names -
  press **TAB** to autofill the top suggestion.
- **Up / Down** browse an open menu; **Shift-TAB** steps back; **Esc** dismisses it.
- **Ctrl-C** clears the current line; **Ctrl-D** (or `exit`) leaves.

---

## Big files

The shell uses the same auto-tuned engine as the CLI, so large files are fine:
schema, row counts and previews read only what they need (a 60-million-row parquet
counts in well under a second), and full writes stream through DuckDB with a live
progress bar. Memory is sized to a fraction of free RAM automatically, so a big job
will not exhaust the machine.

---

## Saving and reusing work

`save clean.dq` writes the pipeline as a recipe. It is a plain text file you can
read, edit and version. Run it again any time, from anywhere:

    kenze run clean.dq

`eject` is the escape hatch: it prints the exact SQL (or a Python snippet) the
pipeline compiles to, so you can paste it into a notebook, a dbt model, or
production - kenze never locks you in. Add a filename to write it straight to a
file: `eject out.sql` or `eject out.py` (the format is taken from the extension,
or say it explicitly with `eject python out.py`).

---

## Everything the CLI can do

The shell covers the whole CLI: single-file cleaning, combine/reshape/split,
integrity checks, ascii `plot` charts, Excel (`.xlsx`) read/write, messy-CSV `skip`,
run `history`, data-quality guards, opening and running saved recipes, and every
power setting (`set` for memory / threads / skip-bad / temp / disk-check, `run`
options for append / errors / log, `load ... as delta|iceberg`). The only thing that
lives outside the shell is the Python API (`import kenze; kenze.to_polars(...)`),
which is a library, not a shell command.

See `DOCS.md` for the full CLI command and flag reference.

## Feedback and bugs

Found a bug, want a command, or hit something confusing? Open an issue at
`https://github.com/Kenzy-Zero/kenze/issues` (the shell prints this link under
`help`). Pull requests are welcome.
