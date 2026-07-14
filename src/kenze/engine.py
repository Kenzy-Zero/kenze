"""DuckDB connection, auto-tuned so big files don't OOM.

The whole anti-OOM story lives here:
  - memory_limit is set to a fraction of *available* RAM (not total), so a
    big job can't grab everything and get OS-killed while other apps run.
    (psutil is a core dependency, so this always works.)
  - temp_directory is set, so DuckDB spills to disk instead of dying when a
    job genuinely needs more than RAM.
  - preserve_insertion_order is off - a real memory saver on large writes.
  - a fixed --memory-limit can pin the budget for reproducible / SLA runs.
  - remote paths (s3://, gs://, https://, ...) transparently load httpfs.
"""
from __future__ import annotations

import os
import tempfile

import duckdb

REMOTE_PREFIXES = (
    "s3://", "gs://", "gcs://", "r2://",
    "az://", "azure://", "abfss://",
    "http://", "https://",
)


def is_remote(path) -> bool:
    return isinstance(path, str) and path.lower().startswith(REMOTE_PREFIXES)


def sql_path(p: str) -> str:
    """Absolute, forward-slashed, single-quote-safe path for embedding in SQL.

    Remote URLs are passed through untouched (only quote-escaped)."""
    if is_remote(p):
        return str(p).replace("'", "''")
    return os.path.abspath(p).replace("\\", "/").replace("'", "''")


def _available_gb():
    try:
        import psutil  # core dependency

        return psutil.virtual_memory().available / 1e9
    except Exception:
        return None


def connect(
    mem_fraction: float = 0.6,
    threads=None,
    temp_dir=None,
    memory_limit_gb=None,
    progress: bool = False,
):
    con = duckdb.connect()
    con.execute(f"SET threads={threads or os.cpu_count() or 4}")

    td = temp_dir or os.path.join(tempfile.gettempdir(), "kenze_spill")
    os.makedirs(td, exist_ok=True)
    con.execute(f"SET temp_directory='{sql_path(td)}'")

    con.execute("SET preserve_insertion_order=false")

    if memory_limit_gb:
        con.execute(f"SET memory_limit='{max(1, int(memory_limit_gb))}GB'")
    else:
        avail = _available_gb()
        if avail:
            con.execute(f"SET memory_limit='{max(1, int(avail * mem_fraction))}GB'")

    if progress:
        for stmt in ("SET enable_progress_bar=true", "SET enable_progress_bar_print=true"):
            try:
                con.execute(stmt)
            except duckdb.Error:
                pass
    return con


def ensure_remote(con, *paths):
    """Load httpfs (and pick up cloud credentials from the environment) the
    first time a remote path is used, so `kenze filter s3://bucket/x.parquet`
    just works without downloading the file first."""
    if not any(is_remote(p) for p in paths if p):
        return
    for stmt in ("INSTALL httpfs", "LOAD httpfs"):
        try:
            con.execute(stmt)
        except duckdb.Error:
            return

    kid = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    region = (os.environ.get("AWS_DEFAULT_REGION")
              or os.environ.get("AWS_REGION") or "us-east-1")
    token = os.environ.get("AWS_SESSION_TOKEN")

    def esc(v):
        return str(v).replace("'", "''")

    try:
        if kid and secret:
            # explicit secret from env keys (no aws extension needed)
            extra = f", SESSION_TOKEN '{esc(token)}'" if token else ""
            con.execute(
                f"CREATE OR REPLACE SECRET kenze_cloud (TYPE S3, "
                f"KEY_ID '{esc(kid)}', SECRET '{esc(secret)}', "
                f"REGION '{esc(region)}'{extra})"
            )
        else:
            # fall back to the standard credential chain (config files, roles)
            con.execute(
                "CREATE SECRET IF NOT EXISTS kenze_cloud "
                "(TYPE S3, PROVIDER credential_chain)"
            )
    except duckdb.Error:
        pass


def temp_dir_of(con) -> str:
    try:
        td = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        if td:
            return td
    except duckdb.Error:
        pass
    return tempfile.gettempdir()
