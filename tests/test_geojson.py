"""GeoJSON read + write (convert both directions). The written GeoJSON is read
back with DuckDB's spatial extension so the geometry assertions reflect reality."""
from __future__ import annotations

import json

import duckdb
import pytest

import kenze
from conftest import _write_csv, fs


@pytest.fixture
def geo(tmp_path):
    """id, city, lat, lon - point data for GeoJSON conversion."""
    rows = [[1, "London", 51.5, -0.12], [2, "Paris", 48.85, 2.35], [3, "Tokyo", 35.68, 139.76]]
    return _write_csv(tmp_path / "geo.csv", ["id", "city", "lat", "lon"], rows)


def _read_geojson(path):
    """-> [(id, x, y), ...] from a written GeoJSON, via DuckDB spatial."""
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial")
    try:
        return con.execute(
            f"SELECT id, ST_X(geom) x, ST_Y(geom) y FROM ST_Read('{fs(path)}') ORDER BY id"
        ).fetchall()
    finally:
        con.close()


def test_csv_to_geojson_autodetect(geo, tmp_path):
    out = fs(tmp_path / "out.geojson")
    n = kenze.sift(geo, out)
    assert n == 3
    rows = _read_geojson(out)
    assert len(rows) == 3
    assert rows[0][0] == 1
    assert abs(rows[0][1] - (-0.12)) < 1e-9    # x = lon
    assert abs(rows[0][2] - 51.5) < 1e-9       # y = lat


def test_csv_to_geojson_explicit_cols(tmp_path):
    src = _write_csv(tmp_path / "odd.csv", ["id", "YY", "XX"], [[1, 10.5, 20.5]])
    out = fs(tmp_path / "odd.geojson")
    kenze.sift(src, out, geo_lat="YY", geo_lon="XX")
    rows = _read_geojson(out)
    assert abs(rows[0][1] - 20.5) < 1e-9 and abs(rows[0][2] - 10.5) < 1e-9


def test_geojson_to_csv_roundtrip(geo, tmp_path, sql):
    gj = fs(tmp_path / "g.geojson")
    kenze.sift(geo, gj)
    back = fs(tmp_path / "back.csv")
    kenze.sift(gj, back)
    rows = sql(f"SELECT id, city, geometry FROM '{back}' ORDER BY id")
    assert len(rows) == 3
    assert rows[0][1] == "London"
    assert "POINT" in rows[0][2].upper()       # geometry preserved as WKT


def test_geojson_needs_geometry(tmp_path):
    src = _write_csv(tmp_path / "plain.csv", ["id", "name"], [[1, "a"]])
    out = fs(tmp_path / "plain.geojson")
    with pytest.raises(ValueError, match="geometry"):
        kenze.sift(src, out)


def test_filter_then_geojson(geo, tmp_path):
    out = fs(tmp_path / "f.geojson")
    n = kenze.sift(geo, out, filter="id > 1")
    assert n == 2
    assert len(_read_geojson(out)) == 2


def test_geojson_geometry_column(tmp_path):
    # a 'coordinates' column holding a GeoJSON geometry object (not lat/lon or WKT)
    poly = json.dumps({"type": "Polygon",
                       "coordinates": [[[55.2, 25.1], [55.3, 25.1], [55.3, 25.2], [55.2, 25.1]]]})
    src = _write_csv(tmp_path / "zones.csv", ["name", "coordinates"], [["Zone A", poly]])
    out = fs(tmp_path / "zones.geojson")
    kenze.sift(src, out)                     # 'coordinates' is auto-detected as the geometry
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial")
    try:
        n, gtype = con.execute(
            f"SELECT count(*), any_value(ST_GeometryType(geom)) FROM ST_Read('{out}')"
        ).fetchone()
    finally:
        con.close()
    assert n == 1 and "POLYGON" in gtype.upper()
