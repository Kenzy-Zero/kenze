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
    init,
    join,
    partition,
    peek,
    pivot,
    profile,
    run_spec,
    run_sql,
    split,
    stats,
    unpivot,
    validate,
)
from .recipe import REFERENCE
from .recipe import parse as parse_recipe

# global flags backfilled after parsing (SUPPRESS keeps them working both
# before AND after the subcommand without clobbering each other)
_GLOBAL_DEFAULTS = {
    "memory_limit": None, "temp_dir": None, "no_disk_check": False,
    "skip_bad_lines": False, "log": None, "quiet": False,
    "dry_run": False, "errors": None, "append": False, "source_format": None,
    "threads": None,
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
    _io(cmd("convert", help="change format (by output extension)"))

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

    cmd("recipe", help="show the recipe (.dq) format and every valid step")
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
    return spec


def _run(a, spec):
    _spec_globals(a, spec)
    con = _con(a)
    try:
        if not a.dry_run:
            print(f"-> {a.cmd}")
        run_spec(spec, con=con, quiet=a.quiet, disk_check=not a.no_disk_check,
                 log=a.log, dry_run=a.dry_run)
    finally:
        con.close()


def _inspect(a):
    """Read-only commands. Returns True if it handled the command."""
    if a.cmd == "recipe":
        print(REFERENCE)
    elif a.cmd == "profile":
        profile(a.input, fmt=a.source_format)
    elif a.cmd == "peek":
        peek(a.input, n=a.n, fmt=a.source_format)
    elif a.cmd == "stats":
        stats(a.input, fmt=a.source_format)
    elif a.cmd == "check":
        check(a.input)
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
    elif a.cmd in _TRANSFORMS:
        attr, key = _TRANSFORMS[a.cmd]
        spec[key] = getattr(a, attr)
    # convert = no transforms, just re-COPY to the new format
    _run(a, spec)


def _dispatch(a):
    if _inspect(a) or _combine(a):
        return
    _transform(a)


def main(argv=None):
    a = build_parser().parse_args(argv)
    for k, v in _GLOBAL_DEFAULTS.items():   # backfill SUPPRESS'd globals
        if not hasattr(a, k):
            setattr(a, k, v)
    try:
        _dispatch(a)
    except (ValueError, FileNotFoundError, OSError, duckdb.Error) as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ncancelled (no partial output was written)")
