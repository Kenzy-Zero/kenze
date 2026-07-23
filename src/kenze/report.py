"""kenze report - turn a data file into a styled HTML/PDF report.

  report mode : one file -> KPI tiles + a ranked table.
  --per-row   : one document per row (batch / mail-merge).
  --scaffold  : write a starter template pre-filled with YOUR columns.

The summary is computed with DuckDB SQL aggregates over the WHOLE file (never-OOM);
the detail table is a bounded top-N so a 60M-row file still renders instantly.
HTML output needs only Jinja2; PDF renders that HTML with the system Chrome/Edge
(zero extra install) and falls back to WeasyPrint if it's installed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .engine import connect
from .ops import _ext, _load_source_ext, _source, ensure_read

MONEY_KW = ("revenue", "sales", "amount", "price", "cost", "salary", "value",
            "spend", "profit", "gmv", "income", "aov")
DELTA_KW = ("pct", "growth", "rate", "change", "delta", "yoy")
AVG_KW = ("avg", "average", "rating", "score", "pct", "growth", "rate", "change", "ratio")
NUMY = ("INT", "DOUBLE", "DECIMAL", "FLOAT", "BIGINT", "HUGEINT", "UINT")


def _jinja():
    try:
        import jinja2
    except ImportError:
        raise ValueError(
            "reports need Jinja2, which isn't installed. Add the report extra:\n"
            "    pip install \"kenze[report]\""
        )
    return jinja2


def _has(name, *keys):
    return any(k in str(name).lower() for k in keys)


def _pretty(c):
    return str(c).replace("_", " ").replace("pct", "%").strip().title()


def _fmt(col, v, currency=""):
    """Human display of a value, inferring format from the column name."""
    if v is None:
        return "-"
    if _has(col, *MONEY_KW):
        return (currency + " " if currency else "") + f"{v:,.0f}"
    if _has(col, *DELTA_KW):
        return f"{v:+.1f}%"
    if isinstance(v, float) and not float(v).is_integer():
        return f"{v:,.1f}"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}"
    return str(v)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def _env(jinja, currency=""):
    env = jinja.Environment(autoescape=True)
    pre = (currency + " ") if currency else ""
    env.filters["money"] = lambda v: (pre + f"{v:,.0f}") if v is not None else "-"
    env.filters["num"] = lambda v: f"{v:,.0f}" if v is not None else "-"
    env.filters["num2"] = lambda v: f"{v:,.2f}" if v is not None else "-"
    env.filters["pct"] = lambda v: f"{v:+.1f}%" if v is not None else "-"
    return env


def _load_theme(name):
    from importlib.resources import files
    root = files("kenze") / "themes"
    tpl = root / f"{name}.html.j2"
    if not tpl.is_file():
        avail = sorted(p.name[:-8] for p in root.iterdir() if p.name.endswith(".html.j2"))
        raise ValueError(f"no built-in theme '{name}'. Available: {', '.join(avail)}")
    return tpl.read_text(encoding="utf-8")


# ---------------------------------------------------------------- context
def _describe(con, src):
    rows = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    return [(r[0], str(r[1]).upper()) for r in rows]


def _stats(con, src, cols):
    out = {}
    for name, typ in cols:
        q = f'"{name.replace(chr(34), chr(34) * 2)}"'
        if any(k in typ for k in NUMY):
            c, s, m, mn, mx = con.execute(
                f"SELECT count({q}), sum({q}), avg({q}), min({q}), max({q}) FROM {src}"
            ).fetchone()
            out[name] = {"count": c, "sum": s, "mean": m, "min": mn, "max": mx}
        else:
            c = con.execute(f"SELECT count({q}) FROM {src}").fetchone()[0]
            out[name] = {"count": c}
    return out


def _context(con, src, meta_over, currency, limit):
    cols = _describe(con, src)
    names = [c for c, _ in cols]
    text_cols = [c for c, t in cols if "VARCHAR" in t]
    num_cols = [c for c, t in cols if any(k in t for k in NUMY)]
    stats = _stats(con, src, cols)

    label_col = text_cols[0] if text_cols else names[0]
    delta_col = next((c for c in num_cols if _has(c, *DELTA_KW)), None)
    ranked = [c for c in num_cols if c != delta_col] or num_cols
    bar_col = max(ranked, key=lambda c: stats[c].get("sum") or 0, default=None)

    # bounded, ranked detail rows (stats above are over the FULL file)
    order = f' ORDER BY "{bar_col}" DESC NULLS LAST' if bar_col else ""
    cur = con.execute(f"SELECT * FROM {src}{order} LIMIT {int(limit)}")
    keys = [d[0] for d in cur.description]
    raw_rows = [dict(zip(keys, r)) for r in cur.fetchall()]
    disp_rows = [{c: _fmt(c, r.get(c), currency) for c in keys} for r in raw_rows]
    table = list(zip(disp_rows, raw_rows))
    max_bar = max((r.get(bar_col) or 0 for r in raw_rows), default=0) if bar_col else 0

    ordered = [label_col] + [c for c in text_cols if c != label_col] + num_cols
    columns = [{"key": c, "label": _pretty(c), "align": "r" if c in num_cols else ""}
               for c in ordered]

    kpi_cols = ([bar_col] if bar_col else []) \
        + [c for c in num_cols if c not in (bar_col, delta_col)] \
        + ([delta_col] if delta_col else [])
    kpis = []
    for c in list(dict.fromkeys(kpi_cols))[:4]:
        use_mean = _has(c, *AVG_KW)
        v = stats[c]["mean"] if use_mean else stats[c]["sum"]
        tone = ("up" if (v or 0) >= 0 else "down") if _has(c, *DELTA_KW) else ""
        pretty = _pretty(c)
        if not use_mean:
            label = "Total " + pretty
        elif pretty.lower().startswith(("avg", "average", "%")) or "%" in pretty:
            label = pretty          # already an average / rate - don't double "Avg"
        else:
            label = "Avg " + pretty
        kpis.append({"label": label, "value": _fmt(c, v, currency), "tone": tone,
                     "note": "blended" if use_mean else "across all records"})

    title = meta_over.get("title") or _pretty(Path(src.strip("'()")).stem)
    meta = {
        "client": meta_over.get("client", title),
        "title": meta_over.get("title", f"{title} Report"),
        "subtitle": meta_over.get("subtitle", f"Summary across {len(raw_rows)} records."),
        "date": meta_over.get("date", ""),
        "period": meta_over.get("period", ""),
        "table_title": meta_over.get("table_title",
                                     f"Detail - ranked by {_pretty(bar_col)}" if bar_col else "Detail"),
    }
    meta.update({k: v for k, v in meta_over.items() if k not in meta})

    return {"rows": raw_rows, "stats": stats, "meta": meta, "columns": columns,
            "kpis": kpis, "table": table, "num_cols": num_cols, "text_cols": text_cols,
            "label_col": label_col, "bar_col": bar_col, "delta_col": delta_col,
            "max_bar": max_bar}


def _row_card(row, ctx, currency):
    tiles = []
    for c in ctx["num_cols"]:
        v = row.get(c)
        tone = ("up" if (v or 0) >= 0 else "down") if _has(c, *DELTA_KW) else ""
        tiles.append({"label": _pretty(c), "value": _fmt(c, v, currency), "tone": tone})
    compare = []
    bar = ctx["bar_col"]
    st = ctx["stats"].get(bar) if bar else None
    if st and st.get("sum"):
        v = row.get(bar) or 0
        d = v - (st.get("mean") or 0)
        compare.append({"label": f"{_pretty(bar)} vs company average",
                        "value": ("+" if d >= 0 else "") + _fmt(bar, d, currency),
                        "tone": "up" if d >= 0 else "down"})
        compare.append({"label": f"Share of total {_pretty(bar)}",
                        "value": f"{v / st['sum'] * 100:.1f}%", "tone": ""})
    subtitle = " - ".join(str(row[c]) for c in ctx["text_cols"]
                          if c != ctx["label_col"] and row.get(c) is not None)
    return {"title": str(row.get(ctx["label_col"], "")), "subtitle": subtitle,
            "tiles": tiles, "compare": compare}


# ---------------------------------------------------------------- scaffold
def scaffold_template(con, src):
    cols = _describe(con, src)
    num = [c for c, t in cols if any(k in t for k in NUMY)]
    L = ["<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">",
         "<title>{{ meta.title }}</title>",
         "<style>",
         "  body{font-family:system-ui,sans-serif;max-width:820px;margin:40px auto;color:#1a1a1a}",
         "  h1{font-size:26px} .tiles{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}",
         "  .tile{border:1px solid #e2e2e2;border-top:3px solid #c79a24;padding:12px 14px;min-width:130px}",
         "  .tile b{font-size:20px;display:block;margin-top:4px}",
         "  table{border-collapse:collapse;width:100%;font-size:13px}",
         "  th,td{border-bottom:1px solid #eee;padding:8px;text-align:left}",
         "</style></head><body>",
         "",
         "<h1>{{ meta.title }}</h1>",
         "<!-- set titles with:  kenze report data.csv -t THIS.html --set title=\"Q1 Review\" -o out.pdf -->",
         "",
         "<div class=\"tiles\">"]
    if not num:
        L.append("  <!-- no numeric columns detected; add tiles as needed -->")
    for c in num:
        L.append(f"  <div class=\"tile\">{_pretty(c)}<b>{{{{ stats.{c}.sum | num }}}}</b></div>")
    L += ["</div>", "",
          "<table><thead><tr>" + "".join(f"<th>{c}</th>" for c, _ in cols) + "</tr></thead>",
          "<tbody>",
          "{% for r in rows %}",
          "  <tr>" + "".join(f"<td>{{{{ r.{c} }}}}</td>" for c, _ in cols) + "</tr>",
          "{% endfor %}",
          "</tbody></table>", "", "</body></html>", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- PDF (system browser)
def _find_browser():
    p = os.environ.get("KENZE_CHROME") or os.environ.get("KENZE_BROWSER")
    if p and os.path.exists(p):
        return p
    cands = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "")):
            if not base:
                continue
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium",
                     "chromium-browser", "microsoft-edge", "microsoft-edge-stable"):
            f = shutil.which(name)
            if f:
                cands.append(f)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def _html_to_pdf(html_path, pdf_path):
    pdf_abs = os.path.abspath(pdf_path)
    url = Path(os.path.abspath(html_path)).as_uri()
    browser = _find_browser()
    if browser:
        udd = tempfile.mkdtemp(prefix="kenze_pdf_")
        try:
            for flag in ("--headless=new", "--headless"):
                cmd = [browser, flag, "--disable-gpu", "--no-first-run",
                       "--no-pdf-header-footer", f"--user-data-dir={udd}",
                       "--virtual-time-budget=8000", f"--print-to-pdf={pdf_abs}", url]
                try:
                    subprocess.run(cmd, timeout=120, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                if os.path.exists(pdf_abs) and os.path.getsize(pdf_abs) > 0:
                    return "chrome/edge"
        finally:
            shutil.rmtree(udd, ignore_errors=True)
    try:
        from weasyprint import HTML
        HTML(os.path.abspath(html_path)).write_pdf(pdf_abs)
        return "weasyprint"
    except ImportError:
        pass
    raise ValueError(
        "couldn't render a PDF: no Chrome/Edge found and WeasyPrint isn't installed.\n"
        "  - install Chrome or Edge (kenze finds it automatically), or\n"
        "  - pip install weasyprint, or\n"
        "  - write .html instead of .pdf (no engine needed)."
    )


# ---------------------------------------------------------------- entry point
def report(input, output=None, template=None, theme="report", per_row=False,
           scaffold=False, fmt_out="html", variables=None, con=None, fmt=None,
           skip=0, limit=500, quiet=False):
    jinja = _jinja()
    variables = variables or {}
    currency = variables.get("currency", "")
    close = False
    if con is None:
        con = connect()
        close = True
    try:
        ensure_read(con, input)
        if fmt:
            _load_source_ext(con, fmt)
        src = _source(input, fmt=fmt, skip=skip or 0)

        if scaffold:
            text = scaffold_template(con, src)
            if output:
                Path(output).write_text(text, encoding="utf-8")
                print(f"-> starter template -> {output}")
            else:
                sys.stdout.write(text)
            return

        ctx = _context(con, src, variables, currency, limit)
        env = _env(jinja, currency)

        name = theme
        if per_row and name == "report":
            name = "scorecard"
        tpl_text = Path(template).read_text(encoding="utf-8") if template else _load_theme(name)
        tpl = env.from_string(tpl_text)

        if per_row:
            outdir = output or (os.path.splitext(input)[0] + "_reports")
            os.makedirs(outdir, exist_ok=True)
            want_pdf = fmt_out == "pdf"
            cur = con.execute(f"SELECT * FROM {src}")
            keys = [d[0] for d in cur.description]
            made, seen = 0, set()
            while True:
                batch = cur.fetchmany(500)
                if not batch:
                    break
                for r in batch:
                    row = dict(zip(keys, r))
                    html = tpl.render(row=row, card=_row_card(row, ctx, currency),
                                      **{k: v for k, v in ctx.items() if k != "rows"},
                                      rows=ctx["rows"])
                    base = _slug(row.get(ctx["label_col"], "")) or f"row_{made + 1}"
                    slug, i = base, 2
                    while slug in seen:
                        slug, i = f"{base}_{i}", i + 1
                    seen.add(slug)
                    hp = os.path.join(outdir, slug + ".html")
                    Path(hp).write_text(html, encoding="utf-8")
                    if want_pdf:
                        _html_to_pdf(hp, os.path.join(outdir, slug + ".pdf"))
                        os.remove(hp)
                    made += 1
            if not quiet:
                print(f"-> {made} {'PDF' if want_pdf else 'HTML'} documents in {outdir}")
            return

        out = output or (os.path.splitext(input)[0] + "_report.html")
        html = tpl.render(**ctx)
        if _ext(out) == ".pdf":
            with tempfile.TemporaryDirectory() as td:
                hp = os.path.join(td, "report.html")
                Path(hp).write_text(html, encoding="utf-8")
                eng = _html_to_pdf(hp, out)
            if not quiet:
                print(f"-> report -> {out}  (rendered via {eng})")
        else:
            Path(out).write_text(html, encoding="utf-8")
            if not quiet:
                print(f"-> report -> {out}")
    finally:
        if close:
            con.close()
