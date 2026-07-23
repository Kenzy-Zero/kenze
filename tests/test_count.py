"""Tests for `kenze count` - no-SQL group-by / value-counts."""
import csv

import pytest

from kenze.engine import connect
from kenze.ops import count


def _data(tmp_path):
    p = tmp_path / "d.csv"
    rows = [{"city": "A", "user": 1}, {"city": "A", "user": 2}, {"city": "A", "user": 2},
            {"city": "B", "user": 3}, {"city": "B", "user": 3}]
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["city", "user"])
        w.writeheader()
        w.writerows(rows)
    return str(p)


def _read(path):
    con = connect()
    rows = con.execute(f"SELECT * FROM '{path}'").fetchall()
    con.close()
    return {r[0]: r[1] for r in rows}


def test_count_to_file(tmp_path):
    out = tmp_path / "c.csv"
    n = count(_data(tmp_path), ["city"], out=str(out), quiet=True)
    assert n == 2
    assert _read(str(out)) == {"A": 3, "B": 2}   # row counts, biggest first


def test_count_distinct(tmp_path):
    out = tmp_path / "c.csv"
    count(_data(tmp_path), ["city"], out=str(out), distinct="user", quiet=True)
    # A has users {1,2} = 2 distinct, B has {3} = 1
    assert _read(str(out)) == {"A": 2, "B": 1}


def test_count_multi_column(tmp_path):
    out = tmp_path / "c.csv"
    n = count(_data(tmp_path), ["city", "user"], out=str(out), quiet=True)
    assert n == 3    # (A,1), (A,2), (B,3)


def test_count_top(tmp_path):
    out = tmp_path / "c.csv"
    n = count(_data(tmp_path), ["city"], out=str(out), top=1, quiet=True)
    assert n == 1
    assert _read(str(out)) == {"A": 3}   # only the biggest group


def test_count_bad_column(tmp_path):
    with pytest.raises(ValueError):
        count(_data(tmp_path), ["nope"], quiet=True)
