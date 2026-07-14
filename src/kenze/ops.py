"""The operations. Each maps a simple intent to a DuckDB SQL fragment, and a
whole recipe compiles to ONE streaming query (not N passes writing N temp
files) - which is what makes it both memory-safe and fast.

Writes are atomic (write to a temp file, rename on success) so a cancelled or
crashed run never leaves a half-written output behind.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time

from .engine import connect, ensure_remote, is_remote, sql_path, temp_dir_of

LAT_NAMES = {"lat", "latitude"}
LON_NAMES = {"lon", "lng", "long", "longitude"}


def _ident(c: str) -> str:
    return '"' + str(c).replace('"', '""') + '"'


def _source(path: str, skip_bad: bool = False) -> str:
    """A FROM-able source for a path.

    DuckDB auto-detects csv / parquet / json (and .gz) by extension. When
    skip_bad is set we read CSVs through read_csv with ignore_errors so a few
    malformed lines don't kill the whole pass.
    """
    p = "'" + sql_path(path) + "'"
    if skip_bad and _ext(path) in ("", ".csv", ".tsv", ".txt", ".gz"):
        return f"read_csv({p}, ignore_errors=true, auto_detect=true)"
    return p


def _ext(path: str) -> str:
    base = path[:-3] if path.lower().endswith(".gz") else path
    return os.path.splitext(base)[1].lower()


def _aslist(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(",") if s.strip()]


def _kv_pairs(v):
    """Parse 'a:b, c:d' (or a list of 'a:b') into [(a, b), ...]."""
    out = []
    for item in _aslist(v):
        if ":" not in item:
            raise ValueError(f"expected 'name:value', got '{item}'")
        k, val = item.split(":", 1)
        out.append((k.strip(), val.strip()))
    return out


def columns(con, source: str):
    return [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]


def _find(cols, names):
    for c in cols:
        if c.lower() in names:
            return c
    return None


def _sql_literal(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # bare number stays numeric; everything else is a quoted string
    try:
        float(s)
        return s
    except ValueError:
        return "'" + s.replace("'", "''") + "'"


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


def _wrap_replace(q: str, items):
    """items = [(col, expr), ...] -> SELECT * REPLACE(expr AS col) FROM (q)."""
    if not items:
        return q
    clause = ", ".join(f"{expr} AS {_ident(col)}" for col, expr in items)
    return f"SELECT * REPLACE ({clause}) FROM ({q}) _q"


def build_query(con, spec) -> str:
    src = _source(spec["input"], skip_bad=spec.get("skip_bad_lines"))
    cols = columns(con, src)

    # base projection
    if spec.get("keep"):
        sel = ", ".join(_ident(c) for c in _aslist(spec["keep"]))
    elif spec.get("drop"):
        drop = _aslist(spec["drop"])
        sel = "* EXCLUDE (" + ", ".join(_ident(c) for c in drop) + ")"
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

    # type casting: types = 'id:VARCHAR, zip:VARCHAR'
    if spec.get("types"):
        casts = [(c, f"CAST({_ident(c)} AS {t})") for c, t in _kv_pairs(spec["types"])]
        q = _wrap_replace(q, casts)

    # fill nulls: fillna = 'city:Unknown, score:0'
    if spec.get("fillna"):
        fills = [
            (c, f"COALESCE({_ident(c)}, {_sql_literal(val)})")
            for c, val in _kv_pairs(spec["fillna"])
        ]
        q = _wrap_replace(q, fills)

    # PII mask: mask = 'email, ssn'  method = hash | redact | null
    if spec.get("mask"):
        method = str(spec.get("mask_method", "hash")).lower()
        items = []
        for c in _aslist(spec["mask"]):
            if method == "redact":
                items.append((c, "'***'"))
            elif method == "null":
                items.append((c, "NULL"))
            else:  # hash (default)
                items.append((c, f"md5(CAST({_ident(c)} AS VARCHAR))"))
        q = _wrap_replace(q, items)

    # rename: rename = 'old:new, old2:new2'
    if spec.get("rename"):
        pairs = ", ".join(f"{_ident(o)} AS {_ident(n)}" for o, n in _kv_pairs(spec["rename"]))
        q = f"SELECT * RENAME ({pairs}) FROM ({q}) _q"

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
    ext = _ext(path)
    gz = path.lower().endswith(".gz")
    if ext in (".parquet", ".pq"):
        return "(FORMAT PARQUET)"
    if ext in (".json", ".ndjson"):
        return "(FORMAT JSON" + (", COMPRESSION 'gzip')" if gz else ")")
    if ext == ".tsv":
        base = "(FORMAT CSV, HEADER, DELIMITER '\t'"
    else:
        base = "(FORMAT CSV, HEADER, DELIMITER ','"  # csv default
    return base + (", COMPRESSION 'gzip')" if gz else ")")


def _disk_check(con, inputs, out, skip=False):
    if skip or out == "-":
        return
    need = 0
    for p in inputs:
        if p and p != "-" and not is_remote(p) and os.path.exists(p):
            need += os.path.getsize(p)
    if need == 0:
        return
    targets = [("temp", temp_dir_of(con))]
    if not is_remote(out):
        targets.append(("output", os.path.dirname(os.path.abspath(out)) or "."))
    for label, d in targets:
        try:
            free = shutil.disk_usage(d).free
        except OSError:
            continue
        if free < need:
            raise ValueError(
                f"not enough free space on the {label} drive ({d}): "
                f"{free / 1e9:.1f} GB free, ~{need / 1e9:.1f} GB may be needed. "
                f"free up space, point --temp-dir elsewhere, or pass --no-disk-check"
            )


def _copy_to(con, query, dst, copy_opts):
    # COPY normally returns a one-row count, but COPY of a PIVOT returns nothing.
    row = con.execute(f"COPY ({query}) TO '{sql_path(dst)}' {copy_opts}").fetchone()
    return row[0] if row else None


def _count_file(con, path):
    try:
        return con.execute(f"SELECT count(*) FROM '{sql_path(path)}'").fetchone()[0]
    except Exception:
        return 0


def _copy(con, query, out, copy_opts):
    """Run COPY ... TO out atomically (temp file + rename); '-' -> stdout."""
    if out == "-":
        tmp = os.path.join(temp_dir_of(con), f"kenze-out-{os.getpid()}.tmp")
        try:
            n = _copy_to(con, query, tmp, copy_opts)
            if n is None:
                n = _count_file(con, tmp)
            try:
                with open(tmp, "rb") as f:
                    shutil.copyfileobj(f, sys.stdout.buffer)
                sys.stdout.buffer.flush()
            except (BrokenPipeError, OSError):
                pass  # a downstream reader (e.g. `head`) closed the pipe early
            # redirect stdout to devnull so the interpreter's exit-time flush
            # can't raise a spurious "Invalid argument" on the closed pipe.
            try:
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            except OSError:
                pass
            return n
        finally:
            _rm(tmp)

    if is_remote(out):
        n = _copy_to(con, query, out, copy_opts)
        return n if n is not None else 0

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    tmp = out + f".kenze-tmp-{os.getpid()}"
    try:
        n = _copy_to(con, query, tmp, copy_opts)
        os.replace(tmp, out)  # atomic on the same filesystem
        return n if n is not None else _count_file(con, out)
    except BaseException:
        _rm(tmp)
        raise


def _rm(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _spool_stdin(temp_dir, fmt="csv"):
    ext = {"csv": ".csv", "tsv": ".tsv", "json": ".json", "parquet": ".parquet"}.get(fmt, ".csv")
    fd, tmp = tempfile.mkstemp(suffix=ext, dir=temp_dir)
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(sys.stdin.buffer, f)
    return tmp


def _write_log(path, payload):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------------ core run

def run_spec(spec, con=None, quiet=False, disk_check=True, log=None) -> int:
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    stdin_tmp = None
    try:
        ensure_remote(con, spec.get("input"), spec.get("output"))
        if spec.get("input") == "-":
            stdin_tmp = _spool_stdin(temp_dir_of(con), spec.get("stdin_format", "csv"))
            spec = {**spec, "input": stdin_tmp}

        t0 = time.time()
        q = build_query(con, spec)
        out = spec["output"]
        _disk_check(con, [spec["input"]], out, skip=not disk_check)
        n = _copy(con, q, out, _copy_opts(out if out != "-" else "out.csv"))
        secs = time.time() - t0
        if not quiet and out != "-":
            print(f"  done: {n:,} rows -> {out}  ({secs:,.1f}s)")
        if log:
            _write_log(log, {
                "tool": "kenze", "action": "run", "input": spec.get("input"),
                "output": out, "rows": n, "seconds": round(secs, 3),
                "steps": {k: spec[k] for k in spec if k not in ("input", "output")},
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        return n
    finally:
        if stdin_tmp:
            _rm(stdin_tmp)
        if own:
            con.close()


def _tty():
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


# --------------------------------------------------------------- inspect ops

def profile(path, con=None) -> int:
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        src = _source(path)
        schema = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        size = os.path.getsize(path) if (not is_remote(path) and os.path.exists(path)) else 0
        print(f"\n  {os.path.basename(path)}")
        print(f"  {n:,} rows  |  {len(schema)} columns  |  {size / 1e9:,.2f} GB on disk\n")
        for row in schema:
            print(f"    {row[0]:<22} {row[1]}")
        print()
        return n
    finally:
        if own:
            con.close()


def stats(path, con=None):
    """Per-column summary (min/max/nulls/approx-unique) via DuckDB SUMMARIZE."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        src = _source(path)
        rows = con.execute(f"SUMMARIZE SELECT * FROM {src}").fetchall()
        cols = [d[0] for d in con.description]
        show = [c for c in ("column_name", "column_type", "min", "max", "approx_unique", "null_percentage") if c in cols]
        idx = [cols.index(c) for c in show]
        widths = [max(len(show[j]), *(len(_s(r[idx[j]])) for r in rows)) for j in range(len(show))]
        header = "  " + "  ".join(h.ljust(widths[j]) for j, h in enumerate(show))
        print("\n" + header)
        print("  " + "  ".join("-" * widths[j] for j in range(len(show))))
        for r in rows:
            print("  " + "  ".join(_s(r[idx[j]]).ljust(widths[j]) for j in range(len(show))))
        print()
        return len(rows)
    finally:
        if own:
            con.close()


def _s(v):
    return "" if v is None else str(v)


def peek(path, n=20, con=None):
    """A quick, zero-dependency look: first N rows as an aligned table,
    plus each column's type and null count (over the sample)."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        src = _source(path)
        schema = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        names = [r[0] for r in schema]
        types = {r[0]: r[1] for r in schema}
        rows = con.execute(f"SELECT * FROM {src} LIMIT {int(n)}").fetchall()
        nulls = {c: sum(1 for r in rows if r[i] is None) for i, c in enumerate(names)}
        cells = [[_s(v) for v in r] for r in rows]
        widths = [
            max(len(names[i]), len(types[names[i]]), *(len(row[i]) for row in cells)) if cells
            else max(len(names[i]), len(types[names[i]]))
            for i in range(len(names))
        ]
        widths = [min(w, 40) for w in widths]

        def line(vals):
            return "  " + "  ".join(_clip(vals[i], widths[i]).ljust(widths[i]) for i in range(len(vals)))

        print(f"\n  {os.path.basename(path)}  (first {len(rows)} rows)\n")
        print(line(names))
        print(line([types[c] for c in names]))
        print("  " + "  ".join("-" * widths[i] for i in range(len(names))))
        for row in cells:
            print(line(row))
        nn = [f"{c}:{nulls[c]}" for c in names if nulls[c]]
        print("\n  nulls in sample: " + (", ".join(nn) if nn else "none") + "\n")
        return len(rows)
    finally:
        if own:
            con.close()


def _clip(s, w):
    return s if len(s) <= w else s[: max(0, w - 1)] + "."


def check(path, con=None) -> int:
    """Pre-flight integrity scan: is the file readable, how many rows, and how
    many rows would be rejected as malformed? Returns the reject count."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        p = "'" + sql_path(path) + "'"
        if _ext(path) in ("", ".csv", ".tsv", ".txt", ".gz"):
            good = con.execute(
                f"SELECT count(*) FROM read_csv({p}, ignore_errors=true, auto_detect=true)"
            ).fetchone()[0]
            try:
                total = con.execute(f"SELECT count(*) FROM {p}").fetchone()[0]
                bad = max(0, total - good)
                verdict = "OK" if bad == 0 else f"{bad:,} malformed row(s) - clean with --skip-bad-lines"
            except Exception:
                bad = -1
                verdict = "readable with --skip-bad-lines (strict read failed)"
            print(f"\n  {os.path.basename(path)}: {good:,} readable rows | {verdict}\n")
            return bad
        n = con.execute(f"SELECT count(*) FROM {p}").fetchone()[0]
        print(f"\n  {os.path.basename(path)}: OK, {n:,} rows, format valid\n")
        return 0
    finally:
        if own:
            con.close()


def validate(path, schema_path, con=None) -> int:
    """Check a file against a target schema JSON:
        {"columns": {"id": "VARCHAR", "amount": "DOUBLE"}, "not_null": ["id"]}
    Prints problems and returns the number of problems (0 = valid)."""
    own = con is None
    con = con or connect()
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        want = {k.lower(): str(v).upper() for k, v in schema.get("columns", {}).items()}
        not_null = [c for c in schema.get("not_null", [])]

        ensure_remote(con, path)
        src = _source(path)
        desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        have = {r[0].lower(): (r[0], str(r[1]).upper()) for r in desc}

        problems = []
        for col, wtype in want.items():
            if col not in have:
                problems.append(f"missing column: {col}")
            elif wtype not in have[col][1] and have[col][1] not in wtype:
                problems.append(f"type mismatch: {have[col][0]} is {have[col][1]}, expected {wtype}")
        for col in not_null:
            match = have.get(col.lower())
            if not match:
                problems.append(f"not-null column absent: {col}")
                continue
            bad = con.execute(f"SELECT count(*) FROM {src} WHERE {_ident(match[0])} IS NULL").fetchone()[0]
            if bad:
                problems.append(f"{bad:,} null(s) in not-null column {match[0]}")

        print(f"\n  validate {os.path.basename(path)} against {os.path.basename(schema_path)}")
        if not problems:
            print("  OK - schema matches\n")
        else:
            for p in problems:
                print(f"  x {p}")
            print()
        return len(problems)
    finally:
        if own:
            con.close()


# ------------------------------------------------------------- combine / diff

def join(left, right, on, how="inner", out=None, con=None, quiet=False, disk_check=True):
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    try:
        ensure_remote(con, left, right, out)
        keys = _aslist(on)
        using = "(" + ", ".join(_ident(k) for k in keys) + ")"
        how_sql = {"inner": "INNER", "left": "LEFT", "right": "RIGHT", "full": "FULL", "outer": "FULL"}
        j = how_sql.get(str(how).lower())
        if not j:
            raise ValueError("--how must be inner | left | right | full")
        q = (
            f"SELECT * FROM {_source(left)} AS l "
            f"{j} JOIN {_source(right)} AS r USING {using}"
        )
        t0 = time.time()
        _disk_check(con, [left, right], out, skip=not disk_check)
        n = _copy(con, q, out, _copy_opts(out if out != "-" else "out.csv"))
        if not quiet and out != "-":
            print(f"  done: {n:,} rows -> {out}  ({time.time() - t0:,.1f}s)")
        return n
    finally:
        if own:
            con.close()


def diff(old, new, on, out=None, con=None):
    """Compare two datasets on a key: how many rows added / removed / changed."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, old, new, out)
        keys = _aslist(on)
        so, sn = _source(old), _source(new)
        ocols = columns(con, so)
        kj = " AND ".join(f"o.{_ident(k)} = n.{_ident(k)}" for k in keys)
        nonkey = [c for c in ocols if c not in keys]
        changed_cond = " OR ".join(
            f"o.{_ident(c)} IS DISTINCT FROM n.{_ident(c)}" for c in nonkey
        ) or "FALSE"

        added = con.execute(
            f"SELECT count(*) FROM {sn} n ANTI JOIN {so} o ON {kj}"
        ).fetchone()[0]
        removed = con.execute(
            f"SELECT count(*) FROM {so} o ANTI JOIN {sn} n ON {kj}"
        ).fetchone()[0]
        changed = con.execute(
            f"SELECT count(*) FROM {so} o JOIN {sn} n ON {kj} WHERE {changed_cond}"
        ).fetchone()[0]

        print(f"\n  diff {os.path.basename(old)} -> {os.path.basename(new)} (on {', '.join(keys)})")
        print(f"    added:   {added:,}")
        print(f"    removed: {removed:,}")
        print(f"    changed: {changed:,}\n")

        if out:
            klist = ", ".join(f"n.{_ident(k)}" for k in keys)
            oklist = ", ".join(f"o.{_ident(k)}" for k in keys)
            q = (
                f"SELECT 'added' AS change, {klist} FROM {sn} n ANTI JOIN {so} o ON {kj} "
                f"UNION ALL SELECT 'removed', {oklist} FROM {so} o ANTI JOIN {sn} n ON {kj} "
                f"UNION ALL SELECT 'changed', {klist} FROM {so} o JOIN {sn} n ON {kj} WHERE {changed_cond}"
            )
            m = _copy(con, q, out, _copy_opts(out))
            print(f"  wrote {m:,} change rows -> {out}\n")
        return added + removed + changed
    finally:
        if own:
            con.close()


def partition(input_path, by, out_dir, fmt="parquet", con=None, quiet=False):
    """Hive-style partitioned output: out_dir/col=value/... via DuckDB PARTITION_BY."""
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    try:
        ensure_remote(con, input_path)
        cols = _aslist(by)
        pcols = "(" + ", ".join(_ident(c) for c in cols) + ")"
        fmt_sql = "PARQUET" if fmt.lower() in ("parquet", "pq") else "CSV"
        opts = f"(FORMAT {fmt_sql}, PARTITION_BY {pcols}, OVERWRITE_OR_IGNORE)"
        dst = "'" + sql_path(out_dir) + "'"
        con.execute(f"COPY (SELECT * FROM {_source(input_path)}) TO {dst} {opts}")
        if not quiet:
            print(f"  done: partitioned by {', '.join(cols)} -> {out_dir}/\n")
        return out_dir
    finally:
        if own:
            con.close()


_AGGS = {"sum", "count", "avg", "mean", "min", "max", "median", "first", "last"}


def pivot(input_path, on, values, agg="sum", group=None, out=None, con=None,
          quiet=False, disk_check=True):
    """Reshape long -> wide: distinct values of `on` become columns, aggregated
    over `values`. e.g. pivot sales ON city USING sum(amount) GROUP BY region."""
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    try:
        ensure_remote(con, input_path, out)
        fn = str(agg).lower()
        fn = "avg" if fn == "mean" else fn
        if fn not in _AGGS:
            raise ValueError(f"--agg must be one of: {', '.join(sorted(_AGGS))}")
        pv = (
            f"PIVOT (SELECT * FROM {_source(input_path)}) "
            f"ON {_ident(on)} USING {fn}({_ident(values)})"
        )
        if group:
            pv += " GROUP BY " + ", ".join(_ident(c) for c in _aslist(group))
        q = f"SELECT * FROM ({pv})"   # wrap so it can be COPY'd
        t0 = time.time()
        _disk_check(con, [input_path], out, skip=not disk_check)
        n = _copy(con, q, out, _copy_opts(out if out != "-" else "out.csv"))
        if not quiet and out != "-":
            print(f"  done: {n:,} rows -> {out}  ({time.time() - t0:,.1f}s)")
        return n
    finally:
        if own:
            con.close()


def run_sql(query, out=None, con=None, quiet=False, disk_check=True):
    """Escape hatch: run any DuckDB SQL (window functions, complex aggregates,
    pivots). Reference files inline, e.g. SELECT * FROM 'big.parquet'."""
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    try:
        if out:
            t0 = time.time()
            n = _copy(con, query, out, _copy_opts(out if out != "-" else "out.csv"))
            if not quiet and out != "-":
                print(f"  done: {n:,} rows -> {out}  ({time.time() - t0:,.1f}s)")
            return n
        rows = con.execute(query).fetchall()
        names = [d[0] for d in con.description]
        print("  " + " | ".join(names))
        for r in rows[:50]:
            print("  " + " | ".join(_s(v) for v in r))
        if len(rows) > 50:
            print(f"  ... {len(rows) - 50:,} more rows")
        return len(rows)
    finally:
        if own:
            con.close()


def eject(spec, to="sql") -> str:
    """Turn a recipe spec into copy-pasteable code (no lock-in)."""
    con = connect()
    try:
        q = build_query(con, spec)
    finally:
        con.close()
    out = spec.get("output", "out.csv")
    if to == "sql":
        return f"COPY (\n  {q}\n) TO '{out}' {_copy_opts(out)};"
    if to == "python":
        return (
            "import duckdb\n"
            "con = duckdb.connect()\n"
            f"con.execute(\"\"\"COPY (\n  {q}\n) TO '{out}' {_copy_opts(out)}\"\"\")\n"
        )
    raise ValueError("--to must be sql | python")


# --------------------------------------------------------------------- split

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(v):
    if v is None:
        return "_null_"
    s = _SAFE_NAME.sub("_", str(v)).strip("_")
    return s or "_blank_"


def split(input_path, by, out_dir, fmt="csv", con=None, max_groups=2000):
    """Write one file per distinct value of column `by` into out_dir."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, input_path)
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
                f"split by a lower-cardinality column, or use `kenze partition`"
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
