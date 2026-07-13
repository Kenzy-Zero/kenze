"""DuckDB connection, auto-tuned so big files don't OOM.

The whole anti-OOM story lives here:
  - memory_limit is set to a fraction of *available* RAM (not total), so a
    big job can't grab everything and get OS-killed while other apps run.
  - temp_directory is set, so DuckDB spills to disk instead of dying when a
    job genuinely needs more than RAM.
  - preserve_insertion_order is off — a real memory saver on large writes.
"""
from __future__ import annotations

import os
import tempfile

import duckdb


def sql_path(p: str) -> str:
    """Absolute, forward-slashed, single-quote-safe path for embedding in SQL."""
    return os.path.abspath(p).replace("\\", "/").replace("'", "''")


def _available_gb():
    try:
        import psutil  # optional extra

        return psutil.virtual_memory().available / 1e9
    except Exception:
        return None


def connect(mem_fraction: float = 0.6, threads=None, temp_dir=None):
    con = duckdb.connect()
    con.execute(f"SET threads={threads or os.cpu_count() or 4}")

    td = temp_dir or os.path.join(tempfile.gettempdir(), "sift_spill")
    os.makedirs(td, exist_ok=True)
    con.execute(f"SET temp_directory='{sql_path(td)}'")

    con.execute("SET preserve_insertion_order=false")

    avail = _available_gb()
    if avail:
        con.execute(f"SET memory_limit='{max(1, int(avail * mem_fraction))}GB'")
    return con
