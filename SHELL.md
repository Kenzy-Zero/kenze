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
| `count [col]` | how many rows the current pipeline produces; `count city` gives a value-counts (top values + counts) of a column |
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
| `sort <col> [desc]` | `sort revenue desc` | order rows by a column (stack with `head` for top-N) |
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
| `convert <name>` | write the current data to a new format by its extension — csv / parquet / json / xlsx / geojson. For GeoJSON, lat/lon columns are auto-detected, or pass `convert out.geojson lat=<col> lon=<col>` |
| `report <out.pdf\|out.html>` | turn the current data into a styled report (KPI tiles + ranked table). Options: `theme=report\|scorecard`, `title=..`, `client=..`, `currency=..`. PDF renders via your system browser. Batch (one doc per row) is CLI-only: `kenze report data.csv --per-row -o dir/`. Needs `pip install "kenze[report]"` |
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
malformed CSV rows, `set strict-csv off` opens a CSV that breaks the standard
outright (mixed line endings, a stray quote — reload the file after changing it),
`set temp <dir>` moves disk-spill, `set disk-check off` skips the pre-flight
free-space check. To read a lakehouse table, `load <path> as delta`
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

## Guided next-step hints

The bottom toolbar tells you **what to type next** for whatever you're doing:

- With nothing loaded it says `load a file to begin` (with an example).
- With a file loaded and an empty line it nudges you to add a step or write an output.
- As you type a command it shows what comes next - e.g. `filter` shows
  `next: a condition   e.g. filter amount > 100`, and once the line is complete it
  flips to `[OK] press Enter to run`. Commands with extras (like `run`, `convert`)
  also list their optional keywords.

So you never have to remember a command's shape: type the command, read the hint,
fill in what it asks for, and press Enter.

## Autocomplete and keys

- Type `/` to open the command menu; keep typing to filter it (`/fi` -> filter).
- **Ghost text** finishes what you are typing as you type it — see below;
  right-arrow accepts.
- Typing a column argument suggests the file's real column names; **TAB** autofills.
- TAB also completes options: `run`/`convert` keywords, `set` settings, and the
  type/method after a colon (`cast id:VARCHAR`, `scale x:zscore`).
- **Up / Down** browse an open menu; **Shift-TAB** steps back; **Esc** dismisses it.
- **Quotes close themselves.** Typing `'` gives you `''` with the cursor in the
  middle, so a text filter types straight through:

      kenze > filter city = '        <- you type one quote
      kenze > filter city = '|'      <- you get the pair, cursor in the middle

  Typing the closing quote steps over the one already there (so you never get
  `'London''`), and backspacing the opening quote removes both. `"` works the
  same way, which is how paths with spaces get typed: `load "Feb 10.csv"`.
  An apostrophe inside a word (`don't`) is left alone.
- **Ctrl-C** clears the current line; **Ctrl-D** (or `exit`) leaves.

### Ghost text

From the very first keystroke, kenze shows the rest of what you are typing in
dim text ahead of the cursor. Press the **right-arrow** (or Ctrl-E) to take it,
or just keep typing to ignore it:

    kenze > f                 -> f`ilter`
    kenze > filter ci         -> filter ci`ty`
    kenze > load data/sal     -> load data/sal`es_2026.csv`
    kenze > set str           -> set str`ict-csv`
    kenze > filter city = 'L  -> filter city = 'L`ondon`

Commands, your file's column names, settings, file paths and — the interesting
one — **the real values in your data**. It keeps up as you **backspace**, so
correcting a wrong guess does not leave you staring at a bare line.

It also works before you have typed the quotes: `filter city = Lon` suggests
`don`, because the shell repairs that shape into valid SQL on Enter anyway. And
when you have named a column but not yet a comparison, `filter city ` offers
`= ` — nobody guesses the operator from a blank prompt.

Two things it deliberately will **not** do:

- **It never finishes a number.** `L` is obviously an unfinished word, so
  completing it to `London` can only help. `id = 1` is already complete and
  valid, and quietly extending it to `10` would change what you asked for while
  looking like it merely finished it. TAB still lists numeric values, because
  there you can see what you are choosing.
- **It says nothing until you have typed a character** (bar the operator case
  above): with an empty value there is no word to finish, and proposing the most
  common one unasked would be putting words in your mouth.

### Value autocomplete

Values are the part kenze has to read your file to know. That happens two ways,
and they answer different questions: ghost text above answers *"what am I
typing?"*, and TAB answers *"what are my options?"* —
**with the true row count beside each value**, most common first:

    kenze > filter city = '<TAB>
                            +--------------------------+
                            | London          600 rows |
                            | Paris           300 rows |
                            | Tokyo           100 rows |
                            +--------------------------+

You no longer have to know what is *in* the file to filter on it. A value
containing an apostrophe is escaped for you either way, so what you end up with
is always valid.

Three things worth knowing, because each is a deliberate choice:

- **The column is read once, on a background thread.** Reading it is a real
  query, so it never runs on the keystroke path: the first suggestion may take a
  moment to appear on a very large file while the prompt keeps taking keys, and
  every one after it is instant.
- **The values follow your pipeline, not the file.** After `filter country =
  'FR'`, the values offered for `city` are the ones that survive that step —
  because anything else would be a confident lie about data you have changed.
- **A high-cardinality column asks for a letter rather than refusing.** An id
  column with four million values is useless as a list and perfectly useful as
  "the ones starting with `u`" — which is how you would look for it anyway. With
  nothing typed, the toolbar tells you what it measured (`~4,182,443 distinct
  values - type a letter to narrow them`); type one and it answers for real,
  refining as you keep going.

The counts are exact. The only estimate involved is the distinct-count used to
decide how to respond, and it is never shown as a fact.

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
power setting (`set` for memory / threads / skip-bad / strict-csv / temp / disk-check, `run`
options for append / errors / log, `load ... as delta|iceberg`). The only thing that
lives outside the shell is the Python API (`import kenze; kenze.to_polars(...)`),
which is a library, not a shell command.

See `DOCS.md` for the full CLI command and flag reference.

## Feedback and bugs

Found a bug, want a command, or hit something confusing? Open an issue at
`https://github.com/Kenzy-Zero/kenze/issues` (the shell prints this link under
`help`). Pull requests are welcome.
