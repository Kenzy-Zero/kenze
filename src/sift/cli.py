"""`dq` command-line front-end. Every subcommand builds a spec and hands it to
the same streaming engine, so a one-liner and a recipe run identically.
"""
from __future__ import annotations

import argparse
import sys

import duckdb

from . import __version__
from .ops import profile, run_spec, split
from .recipe import REFERENCE
from .recipe import parse as parse_recipe


def _io(sp):
    sp.add_argument("input")
    sp.add_argument("-o", "--output", required=True)


def build_parser():
    p = argparse.ArgumentParser(
        prog="dq",
        description="sift - big-file data prep that never runs out of memory (DuckDB-powered).",
    )
    p.add_argument("--version", action="version", version=f"sift {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("profile", help="schema + row count, fast (no full load)")
    sp.add_argument("input")

    sp = sub.add_parser("drop", help="remove columns")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated")

    sp = sub.add_parser("keep", help="keep only these columns")
    _io(sp)
    sp.add_argument("--cols", required=True, help="comma-separated")

    sp = sub.add_parser("filter", help="keep rows matching a SQL condition")
    _io(sp)
    sp.add_argument("--where", required=True)

    sp = sub.add_parser("dedup", help="drop duplicate rows (default: whole-row)")
    _io(sp)
    sp.add_argument("--on", default="all", help="key column(s), comma-separated")

    sp = sub.add_parser("sample", help="random N rows")
    _io(sp)
    sp.add_argument("--n", type=int, required=True)

    sp = sub.add_parser("head", help="first N rows")
    _io(sp)
    sp.add_argument("--n", type=int, required=True)

    sp = sub.add_parser("clip", help="keep only rows inside a lat/lon bounding box")
    _io(sp)
    sp.add_argument("--bbox", required=True, help="min_lon,min_lat,max_lon,max_lat")

    sp = sub.add_parser("convert", help="change format (by output extension)")
    _io(sp)

    sp = sub.add_parser("split", help="split one file into many by a column's values")
    sp.add_argument("input")
    sp.add_argument("--by", required=True, help="column to split on")
    sp.add_argument("-o", "--output", required=True, help="output DIRECTORY")
    sp.add_argument("--format", default="csv", help="csv | parquet | json (default: csv)")

    sp = sub.add_parser("run", help="run a .dq recipe file")
    sp.add_argument("recipe")

    sub.add_parser("recipe", help="show the recipe (.dq) format and every valid step")

    return p


def _dispatch(a):
    if a.cmd == "recipe":
        print(REFERENCE)
        return

    if a.cmd == "profile":
        profile(a.input)
        return

    if a.cmd == "split":
        split(a.input, a.by, a.output, fmt=a.format)
        return

    if a.cmd == "run":
        with open(a.recipe, "r", encoding="utf-8") as f:
            spec = parse_recipe(f.read())
        print(f"-> running recipe {a.recipe}")
        run_spec(spec)
        return

    spec = {"input": a.input, "output": a.output}
    if a.cmd == "drop":
        spec["drop"] = a.cols
    elif a.cmd == "keep":
        spec["keep"] = a.cols
    elif a.cmd == "filter":
        spec["filter"] = a.where
    elif a.cmd == "dedup":
        spec["dedup"] = a.on
    elif a.cmd == "sample":
        spec["sample"] = a.n
    elif a.cmd == "head":
        spec["head"] = a.n
    elif a.cmd == "clip":
        spec["bbox"] = a.bbox
    # convert = no transforms, just re-COPY to the new format

    print(f"-> {a.cmd}")
    run_spec(spec)


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        _dispatch(a)
    except (ValueError, FileNotFoundError, OSError, duckdb.Error) as e:
        # clean one-line message for the user instead of a Python traceback
        sys.exit(f"Error: {e}")
