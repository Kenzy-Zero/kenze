"""The never-OOM engine config: kenze auto-tunes the DuckDB connection so big
jobs spill to disk instead of getting OS-killed."""
from __future__ import annotations

from kenze.engine import connect, is_remote, sql_path


def setting(con, name):
    return con.execute(f"SELECT current_setting('{name}')").fetchone()[0]


def test_connect_sets_disk_spill_and_memory_saver():
    con = connect()
    try:
        # temp_directory set -> DuckDB spills to disk instead of dying
        assert "kenze_spill" in setting(con, "temp_directory")
        # the large-write memory saver is on
        assert str(setting(con, "preserve_insertion_order")).lower() == "false"
        # a memory budget is pinned (not left unbounded)
        assert setting(con, "memory_limit")
    finally:
        con.close()


def test_memory_limit_can_be_pinned():
    con = connect(memory_limit_gb=1)
    try:
        # 1 GB budget -> DuckDB reports it in GiB; the point is it's small/bounded
        val = str(setting(con, "memory_limit"))
        assert "GiB" in val or "MiB" in val
    finally:
        con.close()


def test_is_remote():
    assert is_remote("s3://bucket/x.parquet")
    assert is_remote("https://host/x.csv")
    assert not is_remote("local.csv")


def test_sql_path_forward_slashes_and_escapes_quotes():
    assert "\\" not in sql_path("a/b/c.csv")
    assert sql_path("it's.csv").count("''") == 1     # single quote escaped
    assert sql_path("s3://b/x") == "s3://b/x"          # remote passed through
