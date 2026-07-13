"""The operations. Each maps a simple intent to a DuckDB SQL fragment, and a
whole recipe compiles to ONE streaming query (not N passes writing N temp
files) — which is what makes it both memory-safe and fast.
"""
from __future__ import annotations

import os
import re
import time

from .engine import connect, sql_path

LAT_NAMES = {"lat", "latitude"}
LON_NAMES = {"lon", "lng", "long", "longitude"}


def _ident(c: str) -> str:
    return '"' + str(c).replace('"', '""') + '"'


def _source(path: str) -> str:
    # DuckDB auto-detects csv / parquet / json by extension.
    return "'" + sql_path(path) + "'"


def _aslist(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(",") if s.strip()]


def columns(con, source: str):
    return [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]


def _find(cols, names):
    for c in cols:
        if c.lower() in names:
            return c
    return None


def _clip_sql(spec, cols):
    v = spec.get("bbox")
    if not v:
        return None
    nums = [float(x) for x in v.split(",")] if isinstance(v, str) else [float(x) for x in v]
    if len(nums) != 4:
        raise ValueError("bbox needs 4 numbers: min_lon,min_lat,max_lon,max_lat")
    lat, lon = _find(cols, LAT_NAMES), _find(cols, LON_NAMES)
    if not lat or not lon:
        raise ValueError("clip needs latitude/longitude columns (lat/latitude, lon/longitude)")
    mnlon, mnlat, mxlon, mxlat = nums
    return f"{_ident(lon)} BETWEEN {mnlon} AND {mxlon} AND {_ident(lat)} BETWEEN {mnlat} AND {mxlat}"


def build_query(con, spec) -> str:
    src = _source(spec["input"])
    cols = columns(con, src)

    if spec.get("keep"):
        sel = ", ".join(_ident(c) for c in _aslist(spec["keep"]))
    elif spec.get("drop"):
        drop = {c.lower() for c in _aslist(spec["drop"])}
        sel = ", ".join(_ident(c) for c in cols if c.lower() not in drop)
        if not sel:
            raise ValueError("drop removed every column")
    else:
        sel = "*"

    where = []
    if spec.get("filter"):
        where.append(f"({spec['filter']})")
    clip = _clip_sql(spec, cols)
    if clip:
        where.append(clip)

    q = f"SELECT {sel} FROM {src}"
    if where:
        q += " WHERE " + " AND ".join(where)

    if spec.get("dedup"):
        keys = _aslist(spec["dedup"])
        if [k.lower() for k in keys] == ["all"]:
            q = f"SELECT DISTINCT * FROM ({q}) _q"
        else:
            q = f"SELECT DISTINCT ON ({', '.join(_ident(k) for k in keys)}) * FROM ({q}) _q"

    if spec.get("sample"):
        q = f"SELECT * FROM ({q}) _q USING SAMPLE {int(spec['sample'])} ROWS"

    if spec.get("head"):
        q = f"SELECT * FROM ({q}) _q LIMIT {int(spec['head'])}"

    return q


def _copy_opts(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".tsv":
        return "(HEADER, DELIMITER '\t')"
    if ext in (".parquet", ".pq"):
        return "(FORMAT PARQUET)"
    if ext in (".json", ".ndjson"):
        return "(FORMAT JSON)"
    return "(HEADER, DELIMITER ',')"  # csv default


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(v):
    if v is None:
        return "_null_"
    s = _SAFE_NAME.sub("_", str(v)).strip("_")
    return s or "_blank_"


def _sql_literal(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def split(input_path, by, out_dir, fmt="csv", con=None, max_groups=2000):
    """Write one file per distinct value of column `by` into out_dir."""
    own = con is None
    con = con or connect()
    try:
        src = _source(input_path)
        cols = columns(con, src)
        match = [c for c in cols if c.lower() == by.lower()]
        if not match:
            raise ValueError(f"column '{by}' not found. columns: {', '.join(cols)}")
        col = match[0]

        vals = [r[0] for r in con.execute(f"SELECT DISTINCT {_ident(col)} FROM {src}").fetchall()]
        if len(vals) > max_groups:
            raise ValueError(
                f"'{col}' has {len(vals):,} distinct values (max {max_groups}); "
                f"split by a lower-cardinality column"
            )

        os.makedirs(out_dir, exist_ok=True)
        ext = fmt.lower().lstrip(".")
        opts = _copy_opts(f"_.{ext}")
        used, total = {}, 0
        for v in vals:
            name = _safe_name(v)
            if name in used:
                used[name] += 1
                name = f"{name}_{used[name]}"
            else:
                used[name] = 0
            where = f"{_ident(col)} IS NULL" if v is None else f"{_ident(col)} = {_sql_literal(v)}"
            dst = "'" + sql_path(os.path.join(out_dir, f"{name}.{ext}")) + "'"
            n = con.execute(f"COPY (SELECT * FROM {src} WHERE {where}) TO {dst} {opts}").fetchone()[0]
            total += n
            print(f"  {name}.{ext}: {n:,} rows")
        print(f"  done: {len(vals)} files, {total:,} rows -> {out_dir}")
        return len(vals)
    finally:
        if own:
            con.close()


def run_spec(spec, con=None, quiet=False) -> int:
    own = con is None
    con = con or connect()
    try:
        t0 = time.time()
        q = build_query(con, spec)
        out = spec["output"]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        dst = "'" + sql_path(out) + "'"
        n = con.execute(f"COPY ({q}) TO {dst} {_copy_opts(out)}").fetchone()[0]
        if not quiet:
            print(f"  done: {n:,} rows -> {out}  ({time.time() - t0:,.1f}s)")
        return n
    finally:
        if own:
            con.close()


def profile(path, con=None) -> int:
    own = con is None
    con = con or connect()
    try:
        src = _source(path)
        schema = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"\n  {os.path.basename(path)}")
        print(f"  {n:,} rows  |  {len(schema)} columns  |  {size / 1e9:,.2f} GB on disk\n")
        for row in schema:
            print(f"    {row[0]:<22} {row[1]}")
        print()
        return n
    finally:
        if own:
            con.close()
