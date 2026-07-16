"""Column + row transforms: keep / drop / filter / rename / cast / fillna /
mask / dedup / sample / head / clip / convert. Behaviour is checked against
DuckDB reading the output, so the assertions can't drift from reality."""
from __future__ import annotations

import kenze
from conftest import fs


def cols(sql, path):
    return [r[0] for r in sql(f"DESCRIBE SELECT * FROM '{path}'")]


def count(sql, path):
    return sql(f"SELECT count(*) FROM '{path}'")[0][0]


def test_keep(people, tmp_path, sql):
    out = fs(tmp_path / "k.csv")
    kenze.sift(people, out, keep=["id", "city"])
    assert cols(sql, out) == ["id", "city"]


def test_drop(people, tmp_path, sql):
    out = fs(tmp_path / "d.csv")
    kenze.sift(people, out, drop=["amount"])
    assert "amount" not in cols(sql, out)
    assert "id" in cols(sql, out)


def test_filter_matches_sql(people, tmp_path, sql):
    out = fs(tmp_path / "f.csv")
    n = kenze.sift(people, out, filter="amount > 150")
    expected = sql(f"SELECT count(*) FROM '{people}' WHERE amount > 150")[0][0]
    assert n == expected == count(sql, out)


def test_rename(people, tmp_path, sql):
    out = fs(tmp_path / "r.csv")
    kenze.sift(people, out, rename="amount:total")
    assert "total" in cols(sql, out) and "amount" not in cols(sql, out)


def test_cast_preserves_leading_zero(tmp_path, sql):
    """The zip-code case: casting to VARCHAR keeps a leading zero."""
    src = fs(tmp_path / "zips.csv")
    with open(src, "w", encoding="utf-8") as f:
        f.write("id,zip\n1,01234\n2,90210\n")
    out = fs(tmp_path / "z.csv")
    kenze.sift(src, out, types="zip:VARCHAR")
    zips = [r[0] for r in sql(f"SELECT zip FROM read_csv('{out}', dtypes={{'zip':'VARCHAR'}})")]
    assert "01234" in zips


def test_fillna(people, tmp_path, sql):
    out = fs(tmp_path / "n.csv")
    kenze.sift(people, out, fillna="city:Unknown")
    unknowns = sql(f"SELECT count(*) FROM '{out}' WHERE city = 'Unknown'")[0][0]
    assert unknowns == 1  # the one empty city row


def test_mask_hash_changes_value(people, tmp_path, sql):
    out = fs(tmp_path / "m.csv")
    kenze.sift(people, out, mask="name", mask_method="hash")
    names = {r[0] for r in sql(f"SELECT DISTINCT name FROM '{out}'")}
    assert "Alice" not in names            # original hidden
    assert all(len(str(x)) == 32 for x in names)  # md5 hex


def test_dedup_whole_row(people, tmp_path, sql):
    out = fs(tmp_path / "dd.csv")
    n = kenze.sift(people, out, dedup="all")
    assert n == 11  # 12 rows, one exact duplicate removed


def test_dedup_on_key(people, tmp_path, sql):
    out = fs(tmp_path / "dk.csv")
    kenze.sift(people, out, dedup="id")
    ids = [r[0] for r in sql(f"SELECT id FROM '{out}'")]
    assert len(ids) == len(set(ids)) == 11


def test_head(people, tmp_path, sql):
    out = fs(tmp_path / "h.csv")
    n = kenze.sift(people, out, head=3)
    assert n == 3 == count(sql, out)


def test_sample_size(people, tmp_path, sql):
    out = fs(tmp_path / "s.csv")
    n = kenze.sift(people, out, sample=5)
    assert n == 5


def test_clip_bbox(tmp_path, sql):
    """clip keeps only rows inside a lat/lon box."""
    src = fs(tmp_path / "geo.csv")
    with open(src, "w", encoding="utf-8") as f:
        f.write("id,lat,lon\n1,25.2,55.3\n2,48.8,2.3\n3,25.1,55.2\n")
    out = fs(tmp_path / "g.csv")
    n = kenze.sift(src, out, bbox="54,24,56,26")  # a UAE-ish box
    assert n == 2  # the two ~25/55 rows; Paris (48,2) dropped


def test_convert_csv_to_parquet(people, tmp_path, sql):
    out = fs(tmp_path / "p.parquet")
    kenze.sift(people, out)
    assert count(sql, out) == 12
    assert "id" in cols(sql, out)
