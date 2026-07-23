# kenze documentation

Everything on how to use kenze — as a CLI, an interactive shell, and a Python
library. Start wherever fits what you're doing.

## Start here

- **[Getting started](../README.md)** — install, the shell, the one-liners, the
  full command list, and why it never runs out of memory.

## Guides

| doc | for |
|---|---|
| **[Python API reference](python-api.md)** | using kenze as a **library** (`import kenze`) — every public function with its exact signature, arguments, return value, and an example. |
| **[CLI reference](../DOCS.md)** | the full command-line reference: every command, every flag, the memory model, cloud storage, recipes, and the roadmap. |
| **[Interactive shell](../SHELL.md)** | the `kenze` live session — the `/` command menu, schema-aware autocomplete, building a pipeline step by step, and the guided toolbar. |
| **[Reports](report.md)** | `kenze report` — turn a data file into a styled **PDF / HTML** report (built-in themes, scaffolding, custom templates, one-per-row batch). |

## Reference

- **[Changelog](../CHANGELOG.md)** — what changed in each release.
- **[Contributing](../CONTRIBUTING.md)** — dev setup and how to run the tests.
- **PyPI** — <https://pypi.org/project/kenze/>
- **Issues / feature requests** — <https://github.com/Kenzy-Zero/kenze/issues>

## The three ways to use kenze

```bash
# 1. interactive shell — load once, stack steps that preview live
kenze

# 2. one-line CLI — great for scripts and cron
kenze filter sales.parquet --where "amount > 0" -o big.csv

# 3. Python library
python -c "import kenze; kenze.sift('sales.parquet', 'clean.csv', filter='amount > 0')"
```
