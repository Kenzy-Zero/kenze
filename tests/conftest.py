"""Shared fixtures + helpers for the kenze test suite.

The tests exercise real behaviour end-to-end (they actually read and write
files with DuckDB), so they double as the release regression: if a change
breaks a command, a test here goes red.
"""
from __future__ import annotations

import csv

import duckdb
import pytest


def fs(path) -> str:
    """A forward-slashed, absolute, SQL-embeddable path (Windows-safe)."""
    return str(path).replace("\\", "/")


@pytest.fixture
def sql():
    """Run a DuckDB query and get rows back - used to check kenze's output."""
    con = duckdb.connect()
    try:
        yield lambda q: con.execute(q).fetchall()
    finally:
        con.close()


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return fs(path)


# id, name, city, amount - has a duplicate row (id 2), a null city (id 11),
# and a known city-frequency (London 6 > Paris 3 > Tokyo 2) for onehot/encode.
_PEOPLE = [
    [1, "Alice", "London", 100],
    [2, "Bob", "London", 200],
    [3, "Carol", "London", 150],
    [4, "Dan", "London", 300],
    [5, "Eve", "London", 250],
    [6, "Frank", "Paris", 120],
    [7, "Grace", "Paris", 180],
    [8, "Heidi", "Paris", 90],
    [9, "Ivan", "Tokyo", 400],
    [10, "Judy", "Tokyo", 220],
    [11, "Mallory", "", 60],       # null/empty city
    [2, "Bob", "London", 200],     # exact duplicate of id 2
]


@pytest.fixture
def people(tmp_path):
    """A small people.csv with dups + a null - the general-purpose fixture."""
    return _write_csv(tmp_path / "people.csv", ["id", "name", "city", "amount"], _PEOPLE)


@pytest.fixture
def nums(tmp_path):
    """id, value = 0,10,...,100 (11 clean rows) - for scale / bin / traintest."""
    rows = [[i + 1, i * 10] for i in range(11)]
    return _write_csv(tmp_path / "nums.csv", ["id", "value"], rows)


@pytest.fixture
def outliers(tmp_path):
    """id, value = 1..10 plus one extreme 1000 - for clip-outliers."""
    rows = [[i, i] for i in range(1, 11)] + [[11, 1000]]
    return _write_csv(tmp_path / "outliers.csv", ["id", "value"], rows)
