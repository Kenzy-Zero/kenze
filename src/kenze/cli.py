"""`kenze` command-line front-end. Every transform builds a spec and hands it
to the same streaming engine, so a one-liner and a recipe run identically.
"""
from __future__ import annotations

import argparse
import sys

import duckdb

from . import __version__
from .engine import connect
from .ops import (
    check,
    diff,
    eject,
    history,
    init,
    join,
    partition,
    peek,
    pivot,
    plot,
    profile,
    run_spec,
    run_sql,
    split,
    stats,
    traintest,
    unpivot,
    validate,
)
from .recipe import REFERENCE
from .recipe import parse as parse_recipe
from .report import report

# global flags backfilled after parsing (SUPPRESS keeps them working both
# before AND after the subcommand without clobbering each other)
_GLOBAL_DEFAULTS = {
    "memory_limit": None, "temp_dir": None, "no_disk_check": False,
    "skip_bad_lines": False, "log": None, "quiet": False,
    "dry_run": False, "errors": None, "append": False, "source_format": None,
    "threads": None, "skip": 0, "no_history": False,
}


def _add_globals(parser):
    g = parser.add_argument_group("global options")
    s = argparse.SUPPRESS
    g.add_argument("--memory-limit", type=float, metavar="GB", default=s,
                   help="pin the RAM budget in GB (reproducible runs); default auto-sizes to free RAM")
    g.add_argument("--temp-dir", default=s, help="directory for disk-spill (default: system temp)")
    g.add_argument("--threads", type=int, metavar="N", default=s,
                   help="max threads DuckDB uses (default: all cores)")
    g.add_argument("--no-disk-check", action="store_true", default=s,
                   help="skip the pre-flight free-space check")
    g.add_argument("--skip-bad-lines", action="store_true", default=s,
                   help="ignore malformed rows in CSV input")
    g.add_argument("--skip", type=int, metavar="N", default=s,
                   help="skip N preamble rows before the CSV header (messy exports)")
    g.add_argument("--no-history", action="store_true", default=s,
                   help="don't record this run in ~/.kenze/history.jsonl")
    g.add_argument("--errors", metavar="PATH", default=s,
                   help="quarantine malformed CSV rows to this file instead of failing")
    g.add_argument("--append", action="store_true", default=s,
                   help="append to the output file instead of overwriting (csv/json)")
    g.add_argument("--source-format", metavar="FMT", default=s,
                   help="read a lakehouse table: delta | iceberg")
    g.add_argument("--dry-run", action="store_true", default=s,
                   help="show the compiled query + output schema without running it")
    g.add_argument("--log", metavar="PATH", default=s,
                   help="write a run manifest (json) after a transform")
    g.add_argument("-q", "--quiet", action="store_true", default=s,
                   help="suppress the summary line")


def _io(sp):
    sp.add_argument("input")
    sp.add_argument("-o", "--output", required=True, help="output file (or - for stdout)")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    _add_globals(common)

    p = argparse.ArgumentParser(
        prog="kenze", parents=[common],
        description="kenze - big-file data prep that never runs out of memory (DuckDB-powered).",
    )
    p.add_argument("--version", action="version", version=f"kenze {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    # inspect
    cmd("profile", help="schema + row count, fast (no full load)").add_argument("input")
    sp = cmd("peek", help="preview first rows + types + null counts")
    sp.add_argument("input")
    sp.add_argument("--n", type=int, default=20)
    cmd("stats", help="per-column summary (min/max/nulls/unique)").add_argument("input")
    sp = cmd("plot", help="quick ASCII chart of a column (histogram / bar chart)")
    sp.add_argument("input")
    sp.add_argument("column", help="the column to chart")
    sp.add_argument("--by", help="category column: chart agg(column) per value")
    sp.add_argument("--agg", help="sum | count | avg | min | max | median (default: sum)")
    sp.add_argument("--bins", type=int, default=20, help="histogram bins (numeric, no --by)")
    sp.add_argument("--top", type=int, default=20, help="max bars to show")
    sp.add_argument("--width", type=int, default=48, help="bar width in characters")
    cmd("check", help="pre-flight file-integrity scan").add_argument("input")
    sp = cmd("validate", help="check a file against a target schema json")
    sp.add_argument("input")
    sp.add_argument("--schema", required=True)

    # column ops
    sp = cmd("keep", help="keep only these columns")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated")
    sp = cmd("drop", help="remove columns")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated")
    sp = cmd("rename", help="rename columns")
    _io(sp)
    sp.add_argument("--map", required=True, dest="mapping", help="old:new,old2:new2")
    sp = cmd("cast", help="cast column types (e.g. keep leading zeros)")
    _io(sp)
    sp.add_argument("--types", required=True, help="col:TYPE,col:TYPE")
    sp = cmd("fillna", help="replace nulls in columns with a value")
    _io(sp)
    sp.add_argument("--with", required=True, dest="fill", help="col:value,col:value")
    sp = cmd("mask", help="mask sensitive columns (hash/redact/null)")
    _io(sp)
    sp.add_argument("--cols", required=True)
    sp.add_argument("--method", default="hash")

    # ML-prep (model-ready)
    sp = cmd("scale", help="scale numeric columns for ML (minmax / zscore)")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated numeric columns")
    sp.add_argument("--method", default="minmax", help="minmax | zscore")
    sp = cmd("bin", help="bucket numeric columns into N bins (adds col_bin)")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated numeric columns")
    sp.add_argument("--into", type=int, default=5, help="number of bins (default 5)")
    sp.add_argument("--method", default="uniform", help="uniform | quantile")
    sp = cmd("encode", help="label-encode categorical columns to integers (0-based)")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated columns")
    sp = cmd("onehot", help="one-hot encode categorical columns to 0/1 indicator columns")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated columns")
    sp.add_argument("--max", type=int, default=50, dest="maxcat",
                    help="keep the top-N values as columns, rest -> col_other (default 50)")
    sp = cmd("clip-outliers", help="cap extreme values (winsorize) via IQR or percentile")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated numeric columns")
    sp.add_argument("--method", default="iqr", help="iqr (Tukey 1.5) | pct (1st-99th)")

    # row ops
    sp = cmd("filter", help="keep rows matching a SQL condition")
    _io(sp)
    sp.add_argument("--where", required=True)
    sp = cmd("dedup", help="drop duplicate rows (default: whole-row)")
    _io(sp)
    sp.add_argument("--on", default="all", help="key column(s), comma-separated")
    sp = cmd("sample", help="random N rows")
    _io(sp)
    sp.add_argument("--n", type=int, required=True)
    sp = cmd("head", help="first N rows")
    _io(sp)
    sp.add_argument("--n", type=int, required=True)
    sp = cmd("clip", help="keep only rows inside a lat/lon bounding box")
    _io(sp)
    sp.add_argument("--bbox", required=True,
                    help="min_lon,min_lat,max_lon,max_lat (use --bbox=-10,35,5,45 for negatives)")
    sp = cmd("convert", help="change format by output extension (CSV/Parquet/JSON/Excel/GeoJSON)")
    _io(sp)
    sp.add_argument("--lat", help="latitude column when writing GeoJSON points")
    sp.add_argument("--lon", help="longitude column when writing GeoJSON points")
    sp.add_argument("--geom", help="geometry column when writing GeoJSON (WKT or a GeoJSON-geometry object)")

    # combine / reshape / fan-out
    sp = cmd("join", help="join two files on a key")
    sp.add_argument("left")
    sp.add_argument("right")
    sp.add_argument("--on", required=True, help="key column(s)")
    sp.add_argument("--how", default="inner", help="inner | left | right | full")
    sp.add_argument("-o", "--output", required=True)
    sp = cmd("diff", help="compare two datasets on a key")
    sp.add_argument("old")
    sp.add_argument("new")
    sp.add_argument("--on", required=True)
    sp.add_argument("-o", "--output", help="optional: write the changed keys")
    sp = cmd("split", help="split one file into many by a column's values")
    sp.add_argument("input")
    sp.add_argument("--by", required=True)
    sp.add_argument("-o", "--output", required=True, help="output DIRECTORY")
    sp.add_argument("--format", default="csv", help="csv | parquet | json")
    sp = cmd("partition", help="hive-style partitioned output (col=value/)")
    sp.add_argument("input")
    sp.add_argument("--by", required=True, help="column(s)")
    sp.add_argument("-o", "--output", required=True, help="output DIRECTORY")
    sp.add_argument("--format", default="parquet", help="parquet | csv")
    sp = cmd("traintest", help="split into train/test files (random or time-based)")
    sp.add_argument("input")
    sp.add_argument("-o", "--output", required=True, help="output DIRECTORY")
    sp.add_argument("--ratio", type=float, default=0.8, help="train fraction (default 0.8)")
    sp.add_argument("--seed", type=int, default=42, help="random seed (reproducible)")
    sp.add_argument("--by", help="time column for a leak-free time-based split")
    sp.add_argument("--before", help="rows with by < before -> train, else test")
    sp.add_argument("--format", default="parquet", help="parquet | csv | json")
    sp = cmd("pivot", help="reshape long -> wide (values of a column become columns)")
    sp.add_argument("input")
    sp.add_argument("--on", required=True, help="column whose values become new columns")
    sp.add_argument("--values", required=True, help="column to aggregate")
    sp.add_argument("--agg", default="sum", help="sum | count | avg | min | max | median")
    sp.add_argument("--group", help="row-identity column(s) to keep (optional)")
    sp.add_argument("-o", "--output", required=True)
    sp = cmd("unpivot", help="reshape wide -> long (fold columns into name/value)")
    sp.add_argument("input")
    sp.add_argument("--cols", required=True, help="columns to fold, comma-separated")
    sp.add_argument("--name", default="name", help="new name column (default: name)")
    sp.add_argument("--value", default="value", help="new value column (default: value)")
    sp.add_argument("-o", "--output", required=True)

    # power / interop
    sp = cmd("sql", help="run any DuckDB SQL (window fns, pivots, ...)")
    sp.add_argument("query")
    sp.add_argument("-o", "--output", help="write result (omit to print)")
    sp = cmd("eject", help="turn a recipe into raw SQL / Python (no lock-in)")
    sp.add_argument("recipe")
    sp.add_argument("--to", default="sql", help="sql | python")
    sp = cmd("run", help="run a .dq recipe file")
    sp.add_argument("recipe")
    sp.add_argument("--set", action="append", default=[], metavar="K=V",
                    dest="variables", help="set a recipe variable (repeatable)")

    sp = cmd("init", help="write a starter .dq recipe (scaffolding)")
    sp.add_argument("path", nargs="?", default="recipe.dq")
    sp.add_argument("--input", dest="init_input", help="a data file to pre-fill columns from")

    sp = cmd("history", help="show recent kenze runs (input -> output, rows, time)")
    sp.add_argument("--n", type=int, default=20, help="how many recent runs to show")

    sp = cmd("report", help="turn a data file into a styled HTML/PDF report")
    sp.add_argument("input")
    sp.add_argument("-o", "--output", help="output .html/.pdf file (or a DIRECTORY for --per-row)")
    sp.add_argument("--template", help="your own HTML (Jinja2) template instead of a built-in theme")
    sp.add_argument("--theme", default="report", help="built-in theme: report | scorecard")
    sp.add_argument("--per-row", action="store_true", dest="per_row",
                    help="one document per row (batch / mail-merge)")
    sp.add_argument("--scaffold", action="store_true",
                    help="write a starter template pre-filled with your columns (stdout or -o)")
    sp.add_argument("--format", default="html", dest="report_format",
                    help="--per-row output type: html | pdf (single reports use the -o extension)")
    sp.add_argument("--limit", type=int, default=500, help="max rows in the detail table")
    sp.add_argument("--set", action="append", default=[], dest="report_vars", metavar="K=V",
                    help="template variable, repeatable: title, client, subtitle, currency, date, period")

    cmd("recipe", help="show the recipe (.dq) format and every valid step")
    cmd("shell", help="interactive session: / command menu, live previews, build a recipe")
    return p


def _con(a):
    return connect(
        temp_dir=a.temp_dir,
        memory_limit_gb=a.memory_limit,
        threads=a.threads,
        progress=(not a.quiet) and sys.stderr.isatty(),
    )


def _spec_globals(a, spec):
    spec.setdefault("skip_bad_lines", a.skip_bad_lines)
    if a.errors:
        spec["errors"] = a.errors
    if a.append:
        spec["append"] = True
    if a.source_format:
        spec["source_format"] = a.source_format
    if a.skip:
        spec["skip"] = a.skip
    return spec


def _run(a, spec):
    _spec_globals(a, spec)
    con = _con(a)
    try:
        if not a.dry_run:
            print(f"-> {a.cmd}")
        run_spec(spec, con=con, quiet=a.quiet, disk_check=not a.no_disk_check,
                 log=a.log, dry_run=a.dry_run, action=a.cmd)
    finally:
        con.close()


def _inspect(a):
    """Read-only commands. Returns True if it handled the command."""
    if a.cmd == "recipe":
        print(REFERENCE)
    elif a.cmd == "profile":
        profile(a.input, fmt=a.source_format, skip=a.skip or 0)
    elif a.cmd == "peek":
        peek(a.input, n=a.n, fmt=a.source_format, skip=a.skip or 0)
    elif a.cmd == "stats":
        stats(a.input, fmt=a.source_format, skip=a.skip or 0)
    elif a.cmd == "plot":
        plot(a.input, a.column, by=a.by, agg=a.agg, bins=a.bins, top=a.top,
             width=a.width, fmt=a.source_format)
    elif a.cmd == "check":
        check(a.input)
    elif a.cmd == "history":
        history(n=a.n)
    elif a.cmd == "validate":
        if validate(a.input, a.schema):
            sys.exit(1)
    elif a.cmd == "init":
        init(a.path, input_path=a.init_input)
    else:
        return False
    return True


def _combine(a):
    """Multi-file / fan-out commands. Returns True if it handled the command."""
    if a.cmd == "split":
        split(a.input, a.by, a.output, fmt=a.format)
    elif a.cmd == "partition":
        partition(a.input, a.by, a.output, fmt=a.format, con=_con(a), quiet=a.quiet)
    elif a.cmd == "traintest":
        print("-> traintest")
        traintest(a.input, a.output, ratio=a.ratio, seed=a.seed, by=a.by,
                  before=a.before, fmt=a.format, con=_con(a), quiet=a.quiet)
    elif a.cmd == "pivot":
        print("-> pivot")
        pivot(a.input, a.on, a.values, agg=a.agg, group=a.group, out=a.output,
              con=_con(a), quiet=a.quiet, disk_check=not a.no_disk_check)
    elif a.cmd == "unpivot":
        print("-> unpivot")
        unpivot(a.input, a.cols, name=a.name, value=a.value, out=a.output,
                con=_con(a), quiet=a.quiet, disk_check=not a.no_disk_check)
    elif a.cmd == "join":
        con = _con(a)
        try:
            print("-> join")
            join(a.left, a.right, a.on, how=a.how, out=a.output, con=con,
                 quiet=a.quiet, disk_check=not a.no_disk_check)
        finally:
            con.close()
    elif a.cmd == "diff":
        diff(a.old, a.new, a.on, out=a.output, con=_con(a))
    elif a.cmd == "report":
        report(a.input, output=a.output, template=a.template, theme=a.theme,
               per_row=a.per_row, scaffold=a.scaffold, fmt_out=a.report_format,
               variables=dict(kv.split("=", 1) for kv in a.report_vars if "=" in kv),
               con=_con(a), fmt=a.source_format, skip=a.skip or 0, limit=a.limit,
               quiet=a.quiet)
    elif a.cmd == "sql":
        run_sql(a.query, out=a.output, con=_con(a), quiet=a.quiet, disk_check=not a.no_disk_check)
    elif a.cmd == "eject":
        with open(a.recipe, "r", encoding="utf-8") as f:
            spec = parse_recipe(f.read())
        print(eject(spec, to=a.to))
    elif a.cmd == "run":
        variables = dict(kv.split("=", 1) for kv in a.variables if "=" in kv)
        with open(a.recipe, "r", encoding="utf-8") as f:
            spec = parse_recipe(f.read(), variables=variables)
        _spec_globals(a, spec)
        con = _con(a)
        try:
            if not a.dry_run:
                print(f"-> running recipe {a.recipe}")
            run_spec(spec, con=con, quiet=a.quiet, disk_check=not a.no_disk_check,
                     log=a.log, dry_run=a.dry_run)
        finally:
            con.close()
    else:
        return False
    return True


# cmd -> (attribute on parsed args, key in the spec)
_TRANSFORMS = {
    "drop":   ("cols", "drop"),
    "keep":   ("cols", "keep"),
    "rename": ("mapping", "rename"),
    "cast":   ("types", "types"),
    "fillna": ("fill", "fillna"),
    "filter": ("where", "filter"),
    "dedup":  ("on", "dedup"),
    "clip":   ("bbox", "bbox"),
    "sample": ("n", "sample"),
    "head":   ("n", "head"),
}


def _transform(a):
    spec = {"input": a.input, "output": a.output}
    if a.cmd == "mask":
        spec["mask"] = a.cols
        spec["mask_method"] = a.method
    elif a.cmd == "scale":
        cols = [c.strip() for c in a.cols.split(",") if c.strip()]
        spec["scale"] = ", ".join(f"{c}:{a.method}" for c in cols)
    elif a.cmd == "bin":
        cols = [c.strip() for c in a.cols.split(",") if c.strip()]
        spec["bin"] = ", ".join(f"{c}:{a.into}:{a.method}" for c in cols)
    elif a.cmd == "encode":
        spec["encode"] = ", ".join(c.strip() for c in a.cols.split(",") if c.strip())
    elif a.cmd == "onehot":
        cols = [c.strip() for c in a.cols.split(",") if c.strip()]
        spec["onehot"] = ", ".join(f"{c}:{a.maxcat}" for c in cols)
    elif a.cmd == "clip-outliers":
        cols = [c.strip() for c in a.cols.split(",") if c.strip()]
        spec["clip_outliers"] = ", ".join(f"{c}:{a.method}" for c in cols)
    elif a.cmd in _TRANSFORMS:
        attr, key = _TRANSFORMS[a.cmd]
        spec[key] = getattr(a, attr)
    elif a.cmd == "convert":  # no transforms, just re-COPY to the new format
        for attr, key in (("lat", "geo_lat"), ("lon", "geo_lon"), ("geom", "geo_wkt")):
            if getattr(a, attr, None):
                spec[key] = getattr(a, attr)
    _run(a, spec)


def _dispatch(a):
    if _inspect(a) or _combine(a):
        return
    _transform(a)


def main(argv=None):
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    # `kenze` (no args, interactive terminal) or `kenze shell` -> the session
    if raw and raw[0] == "shell":
        from .shell import run_shell
        return run_shell(raw[1:])
    if not raw and sys.stdin.isatty():
        from .shell import run_shell
        return run_shell()

    a = build_parser().parse_args(raw)
    for k, v in _GLOBAL_DEFAULTS.items():   # backfill SUPPRESS'd globals
        if not hasattr(a, k):
            setattr(a, k, v)
    if getattr(a, "no_history", False):
        import os
        os.environ["KENZE_NO_HISTORY"] = "1"
    try:
        _dispatch(a)
    except (ValueError, FileNotFoundError, OSError, duckdb.Error) as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ncancelled (no partial output was written)")
