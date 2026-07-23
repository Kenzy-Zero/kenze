"""Tests for the `sort` pipeline step (order by, optional top-N via head)."""
import csv

from kenze.engine import connect
from kenze.ops import run_spec


def _data(tmp_path):
    p = tmp_path / "s.csv"
    rows = [{"name": "a", "v": 3}, {"name": "b", "v": 1}, {"name": "c", "v": 2}]
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "v"])
        w.writeheader()
        w.writerows(rows)
    return str(p)


def _names(path):
    con = connect()
    rows = con.execute(f"SELECT name FROM '{path}'").fetchall()
    con.close()
    return [r[0] for r in rows]


def test_sort_desc(tmp_path):
    out = tmp_path / "o.csv"
    run_spec({"input": _data(tmp_path), "sort": "v:desc", "output": str(out)}, quiet=True)
    assert _names(str(out)) == ["a", "c", "b"]      # v = 3, 2, 1


def test_sort_asc(tmp_path):
    out = tmp_path / "o.csv"
    run_spec({"input": _data(tmp_path), "sort": "v", "output": str(out)}, quiet=True)
    assert _names(str(out)) == ["b", "c", "a"]      # v = 1, 2, 3


def test_sort_then_head_is_top_n(tmp_path):
    out = tmp_path / "o.csv"
    run_spec({"input": _data(tmp_path), "sort": "v:desc", "head": 2, "output": str(out)}, quiet=True)
    assert _names(str(out)) == ["a", "c"]           # top 2 by v desc
