"""The Python API surface: kenze.sift / sql / run_spec / build_query, plus the
multi-file ops (join / diff / split / partition / pivot / unpivot / eject) and
the dataframe bridges."""
from __future__ import annotations

import os

import pytest

import kenze
from conftest import fs


def test_sql_returns_rows(people):
    rows = kenze.sql(f"SELECT city, count(*) FROM '{people}' GROUP BY 1 ORDER BY 1")
    got = {c: n for c, n in rows}
    assert got["London"] == 6 and got["Paris"] == 3 and got["Tokyo"] == 2


def test_sift_returns_rowcount(people, tmp_path):
    out = fs(tmp_path / "o.csv")
    assert kenze.sift(people, out, keep=["id"]) == 12


def test_build_query_is_one_streaming_query(people):
    con = kenze.connect()
    try:
        q = kenze.build_query(con, {"input": people, "keep": ["id", "city"],
                                    "filter": "amount > 0", "output": "x.csv"})
        # a single SELECT statement, not N passes / temp tables
        assert q.strip().upper().startswith("SELECT")
        assert q.count(";") == 0
    finally:
        con.close()


def test_profile_counts(people, capsys):
    assert kenze.profile(people) == 12


def test_join(tmp_path, sql):
    a = fs(tmp_path / "a.csv")
    b = fs(tmp_path / "b.csv")
    open(a, "w").write("id,x\n1,a\n2,b\n3,c\n")
    open(b, "w").write("id,y\n2,B\n3,C\n4,D\n")
    out = fs(tmp_path / "j.csv")
    n = kenze.join(a, b, on="id", how="inner", out=out, quiet=True)
    assert n == 2  # ids 2 and 3 in both
    got = {r[0]: (r[1], r[2]) for r in sql(f"SELECT id, x, y FROM '{out}'")}
    assert got[2] == ("b", "B")


def test_diff(tmp_path):
    old = fs(tmp_path / "old.csv")
    new = fs(tmp_path / "new.csv")
    open(old, "w").write("id,v\n1,10\n2,20\n3,30\n")
    open(new, "w").write("id,v\n2,20\n3,99\n4,40\n")   # removed 1, changed 3, added 4
    total = kenze.diff(old, new, on="id")
    assert total == 3  # 1 added + 1 removed + 1 changed


def test_split_by_column(people, tmp_path):
    outdir = tmp_path / "byc"
    n = kenze.split(people, "city", str(outdir))
    files = {f for f in os.listdir(outdir)}
    # London / Paris / Tokyo + the empty city (read as null) -> _null_.csv
    assert n == 4
    assert any(f.startswith("London") for f in files)
    assert "_null_.csv" in files


def test_partition(people, tmp_path, sql):
    outdir = tmp_path / "hive"
    kenze.partition(people, "city", str(outdir), fmt="parquet", quiet=True)
    # hive layout: city=London/ etc.
    subdirs = [d for d in os.listdir(outdir) if d.startswith("city=")]
    assert any("London" in d for d in subdirs)


def test_pivot(tmp_path, sql):
    src = fs(tmp_path / "long.csv")
    open(src, "w").write("region,city,amount\nN,A,10\nN,B,20\nS,A,30\n")
    out = fs(tmp_path / "wide.csv")
    kenze.pivot(src, on="city", values="amount", agg="sum", group="region",
                out=out, quiet=True)
    got = {r[0]: r[1:] for r in sql(f"SELECT * FROM '{out}' ORDER BY region")}
    assert "N" in got  # region kept as row identity


def test_unpivot(tmp_path, sql):
    src = fs(tmp_path / "wide.csv")
    open(src, "w").write("id,jan,feb\n1,10,20\n2,30,40\n")
    out = fs(tmp_path / "long.csv")
    n = kenze.unpivot(src, cols="jan,feb", name="month", value="amt", out=out, quiet=True)
    assert n == 4  # 2 rows x 2 folded columns


def test_eject_to_sql_and_python(people):
    from kenze.ops import eject
    spec = {"input": people, "keep": ["id", "city"], "output": "clean.csv"}
    s = eject(spec, to="sql")
    assert "COPY (" in s and "SELECT" in s.upper()
    p = eject(spec, to="python")
    assert "import duckdb" in p


def test_to_arrow_bridge(people):
    pytest.importorskip("pyarrow")
    tbl = kenze.to_arrow(f"SELECT id, city FROM '{people}'")
    assert tbl.num_rows == 12


def test_to_polars_bridge(people):
    pytest.importorskip("polars")
    df = kenze.to_polars(f"SELECT id FROM '{people}'")
    assert df.height == 12
