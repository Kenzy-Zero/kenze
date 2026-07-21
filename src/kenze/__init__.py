"""kenze - big-file data prep that never runs out of memory.

One `pip install`, then simple commands. DuckDB does the heavy lifting under
the hood (streaming, disk-spill, all cores); kenze just makes it a one-liner
and auto-configures memory so it doesn't OOM.

You can also use it from Python:

    import kenze
    kenze.sift("big.parquet", "clean.csv", keep=["id", "city"],
               filter="amount > 0", sample=50000)
    rows = kenze.sql("SELECT city, count(*) FROM 'big.parquet' GROUP BY 1")
    kenze.profile("big.parquet")
"""
from __future__ import annotations

from .engine import connect
from .ops import (
    build_query,
    check,
    diff,
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
    to_arrow,
    to_df,
    to_polars,
    traintest,
    unpivot,
    validate,
)

__version__ = "0.8.5"


def sift(input, output, con=None, quiet=True, **steps):
    """Run one streaming pass. steps = keep/drop/filter/bbox/types/fillna/
    mask/rename/dedup/sample/head (same words as the recipe / CLI)."""
    spec = {"input": input, "output": output, **steps}
    return run_spec(spec, con=con, quiet=quiet)


def run(recipe_path, variables=None, con=None, quiet=True):
    """Run a .dq recipe file from Python."""
    from .recipe import parse

    with open(recipe_path, encoding="utf-8") as f:
        spec = parse(f.read(), variables=variables)
    return run_spec(spec, con=con, quiet=quiet)


def sql(query, con=None):
    """Run any DuckDB SQL and get the rows back (window functions, aggregates)."""
    own = con is None
    con = con or connect()
    try:
        return con.execute(query).fetchall()
    finally:
        if own:
            con.close()


__all__ = [
    "connect", "sift", "run", "sql", "init",
    "run_spec", "build_query", "run_sql",
    "profile", "stats", "peek", "check", "validate", "plot", "history",
    "join", "diff", "split", "partition", "traintest", "pivot", "unpivot",
    "to_arrow", "to_polars", "to_df",
    "__version__",
]
