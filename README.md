# sift

**Big-file data prep that never runs out of memory - no SQL required.**

`sift` is a tiny command-line tool for cleaning and reshaping data files
(CSV, Parquet, JSON) that are too big for pandas. It's a friendly front-end
over [DuckDB](https://duckdb.org): DuckDB does the heavy lifting (streaming,
disk-spill, all your CPU cores) and `sift` makes it a one-liner - and
auto-configures memory so your job doesn't crash.

```bash
pip install siftq            # pip name; the command is `dq`
```

## Why

- **It doesn't OOM.** Memory is capped to a fraction of *free* RAM and DuckDB
  spills to disk instead of dying. Point it at a file bigger than your RAM; it's fine.
- **No SQL, no pandas.** Simple verbs, or a readable recipe file.
- **One streaming pass.** A whole recipe compiles to a single query - no
  intermediate files, so it's fast and light.
- **Any format.** Reads/writes CSV, Parquet, JSON - auto-detected by extension.

## One-liners

```bash
dq profile sales.parquet                          # schema + row count, instantly
dq keep    sales.parquet --cols id,city,amount -o small.csv
dq drop    users.csv     --cols email,phone    -o clean.parquet
dq filter  sales.parquet --where "amount > 100" -o big.csv
dq dedup   users.csv     --on id               -o unique.parquet
dq sample  sales.parquet --n 50000             -o sample.csv
dq clip    points.parquet --bbox -10,35,5,45    -o region.parquet
dq split   sales.parquet --by city -o by_city/    # one file per distinct value
dq convert sales.parquet -o sales.csv             # just change format
```

## Recipes

Chain steps in a readable `.dq` file - they run as one pass:

```yaml
# clean.dq
input:  data/sales.parquet
keep:   [id, city, amount]
filter: amount > 0
dedup:  id
sample: 50000
output: out/clean.csv
```

```bash
dq run clean.dq
```

## Install with better memory sizing

```bash
pip install "siftq[mem]"       # adds psutil for smarter RAM sizing
```

## Commands

`profile` · `keep` · `drop` · `filter` · `dedup` · `sample` · `head` · `clip` · `split` · `convert` · `run` · `recipe`

## Troubleshooting

**`'dq' is not recognized` / `dq: command not found`?**
`pip` installed siftq correctly (including the `dq` command) - it just landed in a
folder that isn't on your system PATH, so the terminal can't find it. This affects
every pip-installed command-line tool, not just siftq. Options:

- **Use it right now, no setup** - run it as a module:
  ```bash
  python -m sift --help
  ```
- **Fix it for good** - put Python's scripts folder on PATH. Simplest: (re)install
  Python from [python.org](https://www.python.org/downloads/) and tick
  **"Add python.exe to PATH"**. After that, `pip`-installed commands like `dq` just work.
- Prefer an isolated install? Use [pipx](https://pipx.pypa.io) via
  `python -m pipx install siftq` (it manages PATH for you).

## Roadmap

The core stays small and grows release by release: `rename`, `join`,
`stats`, and more. Ideas and issues welcome.

---

> **Naming:** the project is **sift**; it installs from PyPI as **`siftq`**
> (`sift` was taken) and gives you the **`dq`** command.

MIT licensed.
