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

**`dq: command not found` / `'dq' is not recognized`?**
`pip` installed the `dq` launcher into a scripts folder that isn't on your PATH -
a common Python-on-Windows thing, not specific to siftq. Fixes, easiest first:

- Install with **[pipx](https://pipx.pypa.io)**, which puts CLI tools on your PATH automatically:
  ```bash
  pipx install siftq
  ```
- Or run it as a module (works without PATH):
  ```bash
  python -m sift --help
  ```
- Or add the scripts folder shown in `pip`'s install warning to your PATH
  (on Windows you can also reinstall Python with "Add Python to PATH" ticked).

## Roadmap

The core stays small and grows release by release: `rename`, `join`,
`stats`, and more. Ideas and issues welcome.

---

> **Naming:** the project is **sift**; it installs from PyPI as **`siftq`**
> (`sift` was taken) and gives you the **`dq`** command.

MIT licensed.
