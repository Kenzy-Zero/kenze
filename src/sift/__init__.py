"""sift — big-file data prep that never runs out of memory.

One `pip install`, then simple commands. DuckDB does the heavy lifting under
the hood (streaming, disk-spill, all cores); sift just makes it a one-liner
and auto-configures memory so it doesn't OOM.
"""
from .engine import connect
from .ops import run_spec, profile, build_query

__version__ = "0.2.0"
__all__ = ["connect", "run_spec", "profile", "build_query", "__version__"]
