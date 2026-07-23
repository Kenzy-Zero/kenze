# kenze — reports (data file → styled PDF / HTML)

`kenze report` turns a data file into a clean, client-ready **PDF or HTML** report:
a header, KPI tiles, and a ranked table drawn as a bar chart — auto-fit to your
columns. It's the last mile: prep a file with kenze, then hand off something
polished.

**Install the extra once:**

```bash
pip install "kenze[report]"
```

HTML output needs only that (Jinja2). **PDF needs nothing more** — kenze renders
the HTML with the Chrome or Edge already on your machine (falling back to
WeasyPrint if it's installed). No 150 MB browser download, no system libraries.

---

## The three levels of effort

You almost never write a template by hand. There are three levels, and most
people live at level 1.

### 1. Built-in theme (no template at all)

Point it at any file — kenze detects your columns (a label, a headline "revenue"
metric, a growth/percentage column) and lays out the report.

```bash
kenze report sales.csv -o report.pdf                    # PDF
kenze report sales.csv -o report.html                   # HTML (swap the extension)
kenze report sales.csv -o report.pdf --set title="Q1 Review" --set currency=$
```

### 2. Scaffold (kenze writes the template for you)

Generate a starter HTML template **pre-filled with your real column names**, then
tweak it — you never guess placeholders.

```bash
kenze report sales.csv --scaffold -o mine.html
# edit mine.html, then:
kenze report sales.csv --template mine.html -o report.pdf
```

### 3. Custom template (full control)

Bring your own HTML. The placeholder vocabulary is tiny — three things:

| placeholder | is | example |
|---|---|---|
| `{{ r.column }}` | one row's value (inside a table loop) | `{{ r.city }}` |
| `{{ stats.column.sum }}` | a total / average of a column | `{{ stats.revenue.sum }}`, `.mean`, `.min`, `.max` |
| `{{ meta.title }}` | your titles/labels | set with `--set title="…"` |

Plus formatting filters: `| money`, `| num`, `| num2`, `| pct`.

```html
<h1>{{ meta.title }}</h1>
<p>Total revenue: {{ stats.revenue.sum | money }}</p>
<table>{% for r in rows %}<tr><td>{{ r.city }}</td><td>{{ r.revenue | num }}</td></tr>{% endfor %}</table>
```

---

## Batch — one document per row

Add `--per-row` and kenze renders one document **per record** (invoices,
certificates, per-store scorecards). `-o` is a directory.

```bash
kenze report customers.csv --per-row --format pdf -o docs/     # one PDF per row
kenze report customers.csv --per-row --format html -o docs/    # one HTML per row
```

The per-row default theme is `scorecard`; use `--theme scorecard` explicitly, or
your own `--template card.html` where `{{ row.column }}` is the current row.

---

## Full option list

| option | meaning |
|---|---|
| `-o, --output` | output `.html` / `.pdf` file, or a **directory** for `--per-row` |
| `--theme` | built-in theme: `report` (summary) or `scorecard` (per-row card) |
| `--template` | your own HTML (Jinja2) template instead of a theme |
| `--per-row` | one document per row (batch / mail-merge) |
| `--scaffold` | write a starter template from your columns (to stdout or `-o`) |
| `--format` | `--per-row` output type: `html` or `pdf` |
| `--limit` | max rows in the detail table (default 500) |
| `--set K=V` | template variables, repeatable: `title`, `client`, `subtitle`, `currency`, `date`, `period` |

---

## The everyday flow: count → report

A raw file (one row per event) isn't a report on its own — summarise first, then
report. With `count` (no SQL) it's two lines:

```bash
kenze count sales.csv city --top 10 -o city_top10.csv     # summarise: top 10 cities
kenze report city_top10.csv -o cities.pdf --set title="Top 10 Cities"
```

Or shape it live in the shell, then report the result:

```
kenze
load sales.csv
count city            # peek the counts
...
```

---

## Never-OOM on big files

The KPI numbers are DuckDB aggregates over the **whole** file, so they're exact
even on a 60M-row input; the detail table is a bounded top-N (`--limit`), so the
report renders instantly no matter how large the source is.

---

## From Python

```python
from kenze.report import report

report("summary.csv", output="out.pdf",
       variables={"title": "Q1 Review", "client": "Acme", "currency": "$"})

# batch: one PDF per row
report("customers.csv", output="docs/", per_row=True, fmt_out="pdf")
```

---

See also: **[Python API](python-api.md)** · **[CLI reference](../DOCS.md)** · **[shell](../SHELL.md)**.
