"""Data-quality guards - the differentiator. A failing assertion must raise
AND leave NO output file behind (the check runs before anything is written)."""
from __future__ import annotations

import os

import pytest

import kenze
from conftest import fs


def test_assert_unique_passes(people, tmp_path):
    out = fs(tmp_path / "ok.csv")
    # dedup first so ids are unique, then assert it
    n = kenze.run_spec({"input": people, "output": out,
                        "dedup": "id", "assert_unique": "id"}, quiet=True)
    assert n == 11 and os.path.exists(out)


def test_assert_unique_fails_and_writes_nothing(people, tmp_path):
    out = fs(tmp_path / "nope.csv")
    with pytest.raises(ValueError, match="assert_unique"):
        kenze.run_spec({"input": people, "output": out, "assert_unique": "id"}, quiet=True)
    assert not os.path.exists(out)          # <- the guarantee: no corrupt output


def test_assert_not_null_fails_and_writes_nothing(people, tmp_path):
    out = fs(tmp_path / "nn.csv")
    with pytest.raises(ValueError, match="assert_not_null"):
        # city has an empty value -> read as null
        kenze.run_spec({"input": people, "output": out,
                        "filter": "city IS NULL", "assert_not_null": "city"}, quiet=True)
    assert not os.path.exists(out)


def test_assert_row_count_passes(people, tmp_path):
    out = fs(tmp_path / "rc.csv")
    n = kenze.run_spec({"input": people, "output": out, "assert": ["row_count > 0"]}, quiet=True)
    assert n == 12


def test_assert_row_count_fails(people, tmp_path):
    out = fs(tmp_path / "rcf.csv")
    with pytest.raises(ValueError, match="assertion failed"):
        kenze.run_spec({"input": people, "output": out,
                        "filter": "amount > 1000000",     # matches nothing
                        "assert": ["row_count > 0"]}, quiet=True)
    assert not os.path.exists(out)


def test_no_partial_output_on_bad_transform(people, tmp_path):
    """A transform that errors (bad column) must not leave a half-written file."""
    out = fs(tmp_path / "bad.csv")
    with pytest.raises(Exception):
        kenze.run_spec({"input": people, "output": out, "keep": ["does_not_exist"]}, quiet=True)
    assert not os.path.exists(out)
