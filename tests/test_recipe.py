"""The .dq recipe parser + running a recipe end-to-end."""
from __future__ import annotations

import pytest

import kenze
from conftest import fs
from kenze.recipe import parse


def test_parse_basic():
    spec = parse("input: a.csv\nkeep: [id, city]\nfilter: amount > 0\noutput: b.csv\n")
    assert spec["input"] == "a.csv"
    assert spec["keep"] == ["id", "city"]
    assert spec["filter"] == "amount > 0"


def test_parse_keeps_windows_path():
    # split on the FIRST colon so C:\ paths survive
    spec = parse("input: C:\\data\\x.csv\noutput: out.csv\n")
    assert spec["input"].startswith("C:")


def test_comment_inside_quotes_is_kept():
    spec = parse("input: a.csv\nfilter: name = 'a#b'\noutput: b.csv\n")
    assert spec["filter"] == "name = 'a#b'"


def test_unknown_key_raises_with_suggestion():
    with pytest.raises(ValueError, match="filter"):  # 'fitler' -> did you mean filter
        parse("input: a.csv\nfitler: amount > 0\noutput: b.csv\n")


def test_missing_required_raises():
    with pytest.raises(ValueError, match="output"):
        parse("input: a.csv\nkeep: [id]\n")


def test_variables():
    spec = parse("input: sales_${DAY}.csv\noutput: out.csv\n", variables={"DAY": "2026-07-16"})
    assert spec["input"] == "sales_2026-07-16.csv"


def test_multi_assert_keys_accumulate():
    spec = parse("input: a.csv\nassert_not_null: id\nassert_not_null: email\noutput: b.csv\n")
    assert spec["assert_not_null"] == ["id", "email"]


def test_run_recipe_end_to_end(people, tmp_path, sql):
    out = fs(tmp_path / "clean.csv")
    recipe = tmp_path / "r.dq"
    recipe.write_text(
        f"input: {people}\nkeep: [id, city]\nfilter: amount > 100\noutput: {out}\n",
        encoding="utf-8",
    )
    n = kenze.run(str(recipe))
    expected = sql(f"SELECT count(*) FROM '{people}' WHERE amount > 100")[0][0]
    assert n == expected
    assert [r[0] for r in sql(f"DESCRIBE SELECT * FROM '{out}'")] == ["id", "city"]
