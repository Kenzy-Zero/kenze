"""ML-prep commands: scale / bin / encode / onehot / clip-outliers / traintest.
These are pure DuckDB (never-OOM) but must match the semantics an ML engineer
expects from sklearn (minmax in [0,1], zscore mean 0, 0-based label codes, ...)."""
from __future__ import annotations

import os

import kenze
from conftest import fs


def col(sql, path, c):
    return [r[0] for r in sql(f'SELECT "{c}" FROM \'{path}\'')]


def names(sql, path):
    return [r[0] for r in sql(f"DESCRIBE SELECT * FROM '{path}'")]


def test_scale_minmax_in_unit_range(nums, tmp_path, sql):
    out = fs(tmp_path / "mm.csv")
    kenze.sift(nums, out, scale="value:minmax")
    lo, hi = sql(f"SELECT min(value), max(value) FROM '{out}'")[0]
    assert abs(lo - 0.0) < 1e-9 and abs(hi - 1.0) < 1e-9


def test_scale_zscore_mean_zero(nums, tmp_path, sql):
    out = fs(tmp_path / "z.csv")
    kenze.sift(nums, out, scale="value:zscore")
    mean = sql(f"SELECT avg(value) FROM '{out}'")[0][0]
    assert abs(mean) < 1e-9


def test_bin_adds_bucket_column(nums, tmp_path, sql):
    out = fs(tmp_path / "b.csv")
    kenze.sift(nums, out, bin="value:5")
    assert "value_bin" in names(sql, out)
    bins = set(col(sql, out, "value_bin"))
    assert min(bins) >= 1 and max(bins) <= 5


def test_encode_is_zero_based_alphabetical(people, tmp_path, sql):
    out = fs(tmp_path / "e.csv")
    kenze.sift(people, out, encode="city")
    # London < Paris < Tokyo -> 0,1,2 ; the empty city stays NULL
    got = {c: v for c, v in sql(
        f"SELECT name, city FROM '{out}' WHERE name IN ('Alice','Frank','Ivan')")}
    assert got["Alice"] == 0 and got["Frank"] == 1 and got["Ivan"] == 2


def test_onehot_caps_cardinality(people, tmp_path, sql):
    out = fs(tmp_path / "oh.csv")
    kenze.sift(people, out, onehot="city:2")   # top-2 cities keep columns
    ns = names(sql, out)
    assert "city" not in ns                     # original dropped
    assert "city_London" in ns and "city_Paris" in ns
    assert "city_other" in ns                   # Tokyo folded into _other
    # a Tokyo row -> city_other = 1
    row = sql(f"SELECT city_other FROM '{out}' WHERE name = 'Ivan'")[0][0]
    assert row == 1


def test_clip_outliers_caps_extreme(outliers, tmp_path, sql):
    out = fs(tmp_path / "co.csv")
    before = sql(f"SELECT max(value) FROM '{outliers}'")[0][0]
    kenze.sift(outliers, out, clip_outliers="value:iqr")
    after = sql(f"SELECT max(value) FROM '{out}'")[0][0]
    assert before == 1000 and after < 100      # the 1000 got winsorized down


def test_traintest_split_is_disjoint_and_complete(nums, tmp_path, sql):
    outdir = tmp_path / "tt"
    counts = kenze.traintest(nums, str(outdir), ratio=0.7, seed=42, fmt="csv", quiet=True)
    assert set(os.listdir(outdir)) >= {"train.csv", "test.csv"}
    tr = {r[0] for r in sql(f"SELECT id FROM '{fs(outdir / 'train.csv')}'")}
    te = {r[0] for r in sql(f"SELECT id FROM '{fs(outdir / 'test.csv')}'")}
    assert tr & te == set()                     # no row in both
    assert tr | te == set(range(1, 12))         # every row placed
    assert counts["train"] + counts["test"] == 11


def test_traintest_is_reproducible(nums, tmp_path, sql):
    a = kenze.traintest(nums, str(tmp_path / "a"), ratio=0.7, seed=7, fmt="csv", quiet=True)
    b = kenze.traintest(nums, str(tmp_path / "b"), ratio=0.7, seed=7, fmt="csv", quiet=True)
    assert a == b                               # same seed -> identical split
