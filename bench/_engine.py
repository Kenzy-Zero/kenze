"""Run ONE engine's version of the benchmark task, in its own process.

Task: read a big CSV -> filter (value > 0.5) -> group by category
      -> sum(value), avg(value2), count -> write the small result.

pandas / polars-eager have no built-in memory limit, so they're hard-capped to
the given budget with RLIMIT_AS - that models "a machine with N GB of RAM".
kenze is given the SAME budget through its own --memory-limit and spills the
overflow to disk; that self-limiting IS the feature under test, so it isn't
RLIMIT-capped (its disk-spill temp files would otherwise count against the cap).

Exit 0 = finished. A non-zero exit / MemoryError = ran out of memory.
"""
from __future__ import annotations

import argparse
import sys
import time


def _hard_cap(mem_gb: float) -> None:
    """Cap this process's address space (Linux/mac). No-op on Windows."""
    try:
        import resource
        b = int(mem_gb * (1024 ** 3))
        resource.setrlimit(resource.RLIMIT_AS, (b, b))
    except Exception:
        pass


def run_pandas(inp: str, out: str) -> int:
    import pandas as pd
    df = pd.read_csv(inp)                      # eager: loads the whole file
    r = (df[df["value"] > 0.5]
         .groupby("category")
         .agg(n=("value", "size"), total=("value", "sum"), avg2=("value2", "mean"))
         .reset_index())
    r.to_csv(out, index=False)
    return len(r)


def run_polars(inp: str, out: str) -> int:
    import polars as pl
    (pl.scan_csv(inp)                          # lazy + streaming
       .filter(pl.col("value") > 0.5)
       .group_by("category")
       .agg(pl.len().alias("n"),
            pl.col("value").sum().alias("total"),
            pl.col("value2").mean().alias("avg2"))
       .sink_csv(out))
    return 0


def run_kenze(inp: str, out: str, mem_gb: float) -> int:
    import kenze
    con = kenze.connect(memory_limit_gb=(mem_gb or None))
    p = inp.replace("\\", "/")
    q = (f"SELECT category, count(*) AS n, sum(value) AS total, avg(value2) AS avg2 "
         f"FROM '{p}' WHERE value > 0.5 GROUP BY category")
    try:
        return kenze.run_sql(q, out=out, con=con, quiet=True)
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["pandas", "polars", "kenze"])
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--mem-gb", type=float, default=0.0)
    a = ap.parse_args()

    # pandas / eager engines get the OS cap; kenze self-limits instead.
    if a.mem_gb and a.engine in ("pandas", "polars"):
        _hard_cap(a.mem_gb)

    t0 = time.time()
    try:
        if a.engine == "pandas":
            rows = run_pandas(a.input, a.output)
        elif a.engine == "polars":
            rows = run_polars(a.input, a.output)
        else:
            rows = run_kenze(a.input, a.output, a.mem_gb)
    except MemoryError:
        print("MemoryError", file=sys.stderr)
        return 137
    print(f"OK rows={rows} secs={time.time() - t0:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
