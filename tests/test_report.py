"""Tests for `kenze report` - data file -> styled HTML report, and the batch /
scaffold / theme paths. PDF rendering (system browser) is not exercised here;
we assert the HTML the PDF is made from, which is where the content lives."""
import csv
import os

import pytest

from kenze.engine import connect
from kenze.ops import _source
from kenze.report import _context, _fmt, report, scaffold_template


def _data(tmp_path):
    p = tmp_path / "stores.csv"
    rows = [
        {"store": "A", "region": "North", "orders": 100, "revenue": 5000.0, "growth_pct": 12.5},
        {"store": "B", "region": "South", "orders": 50, "revenue": 9000.0, "growth_pct": -3.0},
        {"store": "C", "region": "North", "orders": 80, "revenue": 2000.0, "growth_pct": 7.0},
    ]
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return str(p)


def test_fmt_infers_by_column_name():
    assert _fmt("revenue", 12345.6, "AED") == "AED 12,346"
    assert _fmt("growth_pct", 12.5) == "+12.5%"
    assert _fmt("growth_pct", -3.0) == "-3.0%"
    assert _fmt("orders", 1000) == "1,000"
    assert _fmt("rating", 4.25) == "4.2"
    assert _fmt("anything", None) == "-"


def test_context_detects_roles(tmp_path):
    con = connect()
    src = _source(_data(tmp_path))
    ctx = _context(con, src, {}, "AED", 500)
    assert ctx["label_col"] == "store"          # first text column
    assert ctx["bar_col"] == "revenue"          # biggest-sum numeric
    assert ctx["delta_col"] == "growth_pct"     # the pct/growth column
    # stats are over the WHOLE file
    assert ctx["stats"]["revenue"]["sum"] == 16000.0
    assert ctx["stats"]["orders"]["sum"] == 230
    # rows ranked by the bar column, descending
    assert [r["store"] for r in ctx["rows"]] == ["B", "A", "C"]
    con.close()


def test_report_html_output(tmp_path):
    src = _data(tmp_path)
    out = tmp_path / "r.html"
    report(src, output=str(out), variables={"title": "My Report", "currency": "AED"}, quiet=True)
    html = out.read_text(encoding="utf-8")
    assert "My Report" in html
    assert "AED 16,000" in html            # total revenue KPI
    assert "Store" in html and "Growth %" in html
    # ranked table content present
    assert html.index("A") and "North" in html


def test_report_default_output_path(tmp_path):
    src = _data(tmp_path)
    report(src, variables={"currency": "AED"}, quiet=True)
    assert os.path.exists(os.path.splitext(src)[0] + "_report.html")


def test_report_per_row_batch(tmp_path):
    src = _data(tmp_path)
    outdir = tmp_path / "cards"
    report(src, output=str(outdir), per_row=True, fmt_out="html",
           variables={"currency": "AED"}, quiet=True)
    made = sorted(os.listdir(outdir))
    assert made == ["a.html", "b.html", "c.html"]
    a = (outdir / "a.html").read_text(encoding="utf-8")
    assert "AED 5,000" in a                 # this row's revenue
    assert "Share of total" in a            # the vs-company compare line


def test_report_scaffold_writes_placeholders(tmp_path):
    con = connect()
    src = _source(_data(tmp_path))
    tpl = scaffold_template(con, src)
    con.close()
    assert "{{ meta.title }}" in tpl
    assert "{{ r.store }}" in tpl
    assert "{{ stats.revenue.sum | num }}" in tpl   # numeric cols get a stat tile
    assert "{{ stats.store" not in tpl              # text cols do NOT


def test_report_custom_template(tmp_path):
    src = _data(tmp_path)
    tpl = tmp_path / "t.html"
    tpl.write_text("<h1>{{ meta.title }}</h1><p>{{ stats.revenue.sum | money }}</p>"
                   "{% for r in rows %}<i>{{ r.store }}</i>{% endfor %}", encoding="utf-8")
    out = tmp_path / "c.html"
    report(src, output=str(out), template=str(tpl),
           variables={"title": "Custom", "currency": "$"}, quiet=True)
    html = out.read_text(encoding="utf-8")
    assert "<h1>Custom</h1>" in html
    assert "$ 16,000" in html
    assert "<i>B</i>" in html


def test_report_unknown_theme_errors(tmp_path):
    with pytest.raises(ValueError):
        report(_data(tmp_path), output=str(tmp_path / "x.html"), theme="nope", quiet=True)
