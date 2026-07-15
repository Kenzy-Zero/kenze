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

from .engine import connect, ensure_remote, is_remote, load_extension, sql_path, temp_dir_of

LAT_NAMES = {"lat", "latitude"}
LON_NAMES = {"lon", "lng", "long", "longitude"}


def _ident(c: str) -> str:
    return '"' + str(c).replace('"', '""') + '"'


REJECTS_TABLE = "kenze_rejects"


def _is_glob(path) -> bool:
    return isinstance(path, str) and any(c in path for c in "*?[")


def _source(path: str, skip_bad: bool = False, fmt: str = None,
            errors: bool = False, skip: int = 0) -> str:
    """A FROM-able source for a path.

    DuckDB auto-detects csv / parquet / json (and .gz) by extension; .xlsx / .xls
    are read via read_xlsx (the caller loads the excel extension). A `fmt` of
    'delta' or 'iceberg' reads a lakehouse table (extension loaded by the caller).
    `skip_bad` ignores malformed CSV rows; `errors` also quarantines them; `skip`
    drops N preamble rows before the header. When the path is a glob
    (sales_*.csv), union_by_name aligns columns across files so a schema mismatch
    between files doesn't crash the run.
    """
    p = "'" + sql_path(path) + "'"
    if fmt in ("delta", "deltalake"):
        return f"delta_scan({p})"
    if fmt == "iceberg":
        return f"iceberg_scan({p})"

    e = _ext(path)
    if e in (".xlsx", ".xls"):
        return f"read_xlsx({p})"

    glob = _is_glob(path)
    is_csvish = e in ("", ".csv", ".tsv", ".txt", ".gz")

    if is_csvish and (errors or skip_bad or glob or skip):
        opts = ["auto_detect=true"]
        if glob:
            opts.append("union_by_name=true")
        if skip:
            # messy exports often have comment/blank preamble lines that trip the
            # strict CSV sniffer even after skipping - relax it for skip mode.
            opts.append(f"skip={int(skip)}")
            opts.append("strict_mode=false")
        if errors:
            opts += ["ignore_errors=true", "store_rejects=true", f"rejects_table='{REJECTS_TABLE}'"]
        elif skip_bad:
            opts.append("ignore_errors=true")
        return f"read_csv({p}, {', '.join(opts)})"
    if glob and e in (".parquet", ".pq"):
        return f"read_parquet({p}, union_by_name=true)"
    if glob and e in (".json", ".ndjson"):
        return f"read_json({p}, union_by_name=true)"
    return p


def _is_excel(path) -> bool:
    return isinstance(path, str) and _ext(path) in (".xlsx", ".xls")


def ensure_excel(con, *paths):
    """Load the DuckDB excel extension the first time an .xlsx path is used, so
    reading and writing Excel workbooks just works."""
    if any(_is_excel(p) for p in paths if p):
        load_extension(con, "excel")


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
    src = _source(spec["input"], skip_bad=spec.get("skip_bad_lines"),
                  fmt=spec.get("source_format"), errors=bool(spec.get("errors")),
                  skip=spec.get("skip") or 0)
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
    if ext in (".xlsx", ".xls"):
        return "(FORMAT xlsx, HEADER true)"
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
        return con.execute(f"SELECT count(*) FROM {_source(path)}").fetchone()[0]
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


# ---------------------------------------------------------------- run history

_HISTORY_CAP = 2000   # keep the ledger from growing without bound


def _history_path() -> str:
    base = os.environ.get("KENZE_HOME") or os.path.join(os.path.expanduser("~"), ".kenze")
    return os.path.join(base, "history.jsonl")


def record_history(action, inp=None, out=None, rows=None, seconds=None, extra=None):
    """Append one line to the local run ledger (~/.kenze/history.jsonl). Silent
    and best-effort - never fails a run. Disable with KENZE_NO_HISTORY=1."""
    if os.environ.get("KENZE_NO_HISTORY"):
        return
    try:
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": action}
        if inp is not None and inp != "-":
            rec["input"] = inp
        if out is not None and out != "-":
            rec["output"] = out
        if rows is not None:
            rec["rows"] = rows
        if seconds is not None:
            rec["seconds"] = round(seconds, 3)
        if extra:
            rec.update(extra)
        path = _history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        _trim_history(path)
    except Exception:
        pass


def _trim_history(path):
    try:
        if os.path.getsize(path) < 400_000:
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _HISTORY_CAP:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-_HISTORY_CAP:])
    except OSError:
        pass


def history(n=20, con=None) -> int:
    """Show the last N recorded runs (input -> output, rows, time)."""
    path = _history_path()
    if not os.path.exists(path):
        print("\n  no run history yet - it fills in as you run kenze.\n")
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = [ln for ln in f if ln.strip()]
    except OSError:
        print("\n  could not read the history file.\n")
        return 0
    recs = []
    for ln in raw[-int(n):]:
        try:
            recs.append(json.loads(ln))
        except Exception:
            pass
    if not recs:
        print("\n  no run history yet.\n")
        return 0
    rendered = []
    for r in recs:
        io = os.path.basename(str(r["input"])) if r.get("input") else ""
        if r.get("output"):
            io = (io + " -> " if io else "") + os.path.basename(str(r["output"]))
        rows = f"{r['rows']:,} rows" if isinstance(r.get("rows"), int) else ""
        secs = f"{r['seconds']:.1f}s" if isinstance(r.get("seconds"), (int, float)) else ""
        tail = ", ".join(x for x in (rows, secs) if x)
        when = str(r.get("at", "")).replace("T", " ")[:16]
        rendered.append((when, str(r.get("action", "")), io, f"({tail})" if tail else ""))

    aw = max((len(a) for _, a, _, _ in rendered), default=1)
    iw = min(40, max((len(i) for _, _, i, _ in rendered), default=1))
    print(f"\n  last {len(recs)} run(s)   ({path})\n")
    for when, act, io, tail in rendered:
        io_show = io if len(io) <= iw else io[: iw - 1] + "."
        print(f"  {when}  {act.ljust(aw)}  {io_show.ljust(iw)}  {tail}")
    print()
    return len(recs)


def _load_source_ext(con, fmt):
    if fmt in ("delta", "deltalake"):
        load_extension(con, "delta")
    elif fmt == "iceberg":
        load_extension(con, "iceberg")


def _explain(con, q, out):
    """--dry-run: show what WOULD run (compiled query + output schema), no execution."""
    print("\n  DRY RUN - nothing was executed.")
    print(f"  would write to: {out}\n")
    print("  compiled query:")
    print(f"    {q}\n")
    try:
        schema = con.execute(f"DESCRIBE {q}").fetchall()
        print("  output schema:")
        for row in schema:
            print(f"    {row[0]:<24} {row[1]}")
        print()
    except Exception:
        pass


def _dump_rejects(con, errpath):
    """Write the quarantined bad CSV rows to errpath; return how many."""
    try:
        n = con.execute(f"SELECT count(*) FROM {REJECTS_TABLE}").fetchone()[0]
    except Exception:
        return 0
    if not n:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(errpath)) or ".", exist_ok=True)
    con.execute(
        f"COPY (SELECT * FROM {REJECTS_TABLE}) TO '{sql_path(errpath)}' {_copy_opts(errpath)}"
    )
    return n


def _copy_append(con, query, out, copy_opts):
    """Append rows to an existing csv/tsv/json file (create it if missing)."""
    if _ext(out) in (".parquet", ".pq") or out.lower().endswith(".gz"):
        raise ValueError("append is only supported for plain csv/tsv/json outputs")
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        return _copy(con, query, out, copy_opts)
    tmp = out + f".kenze-app-{os.getpid()}"
    try:
        n = _copy_to(con, query, tmp, copy_opts)
        n = n if n is not None else _count_file(con, tmp)
        strip_header = _ext(out) in ("", ".csv", ".tsv", ".txt")
        with open(tmp, "rb") as f:
            if strip_header:
                f.readline()  # drop the new chunk's header row
            data = f.read()
        with open(out, "ab") as g:
            g.write(data)
        return n
    finally:
        _rm(tmp)


def _as_multi(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _run_asserts(con, q, spec):
    """Fail (raise) if any recipe assertion doesn't hold. Runs BEFORE the write,
    so a failed check aborts with no output."""
    for cond in _as_multi(spec.get("assert")):
        cond = cond if isinstance(cond, str) else " ".join(map(str, cond))
        ok = con.execute(
            f"SELECT ({cond}) FROM (SELECT count(*) AS row_count FROM ({q}) _q) _a"
        ).fetchone()[0]
        if not ok:
            raise ValueError(f"assertion failed: {cond}")
    for item in _as_multi(spec.get("assert_unique")):
        cols = _aslist(item)
        cl = ", ".join(_ident(c) for c in cols)
        dups = con.execute(
            f"SELECT count(*) FROM (SELECT {cl} FROM ({q}) _q GROUP BY {cl} HAVING count(*) > 1) _d"
        ).fetchone()[0]
        if dups:
            raise ValueError(f"assert_unique failed: {dups:,} duplicate key(s) in ({', '.join(cols)})")
    for item in _as_multi(spec.get("assert_not_null")):
        for c in _aslist(item):
            nn = con.execute(f"SELECT count(*) FROM ({q}) _q WHERE {_ident(c)} IS NULL").fetchone()[0]
            if nn:
                raise ValueError(f"assert_not_null failed: {nn:,} null(s) in column {c}")


def _schema_of(con, sql):
    try:
        return {r[0]: r[1] for r in con.execute(f"DESCRIBE {sql}").fetchall()}
    except Exception:
        return None


# ------------------------------------------------------------------ core run

def run_spec(spec, con=None, quiet=False, disk_check=True, log=None, dry_run=False,
             action="run") -> int:
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    stdin_tmp = None
    try:
        ensure_remote(con, spec.get("input"), spec.get("output"))
        ensure_excel(con, spec.get("input"), spec.get("output"))
        _load_source_ext(con, spec.get("source_format"))
        if spec.get("input") == "-":
            stdin_tmp = _spool_stdin(temp_dir_of(con), spec.get("stdin_format", "csv"))
            spec = {**spec, "input": stdin_tmp}

        t0 = time.time()
        q = build_query(con, spec)
        out = spec["output"]
        if dry_run:
            _explain(con, q, out)
            return 0

        _run_asserts(con, q, spec)   # fail before writing anything
        _disk_check(con, [spec["input"]], out, skip=not disk_check)
        opts = _copy_opts(out if out != "-" else "out.csv")
        if spec.get("append") and out != "-" and not is_remote(out):
            n = _copy_append(con, q, out, opts)
        else:
            n = _copy(con, q, out, opts)

        nbad = _dump_rejects(con, spec["errors"]) if spec.get("errors") and out != "-" else 0
        secs = time.time() - t0
        if not quiet and out != "-":
            extra = f"  ({nbad:,} bad rows -> {spec['errors']})" if nbad else ""
            print(f"  done: {n:,} rows -> {out}  ({secs:,.1f}s){extra}")
        if log:
            in_src = _source(spec["input"], skip_bad=spec.get("skip_bad_lines"),
                             fmt=spec.get("source_format"), errors=bool(spec.get("errors")))
            _write_log(log, {
                "tool": "kenze", "action": "run", "input": spec.get("input"),
                "output": out, "rows": n, "bad_rows": nbad, "seconds": round(secs, 3),
                "steps": {k: spec[k] for k in spec if k not in ("input", "output")},
                "input_schema": _schema_of(con, f"SELECT * FROM {in_src}"),
                "output_schema": _schema_of(con, q),
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        record_history(action, spec.get("input"), out, n, secs)
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

def profile(path, con=None, fmt=None, skip=0) -> int:
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        ensure_excel(con, path)
        _load_source_ext(con, fmt)
        src = _source(path, fmt=fmt, skip=skip)
        schema = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        size = os.path.getsize(path) if (not is_remote(path) and os.path.isfile(path)) else 0
        print(f"\n  {os.path.basename(path)}")
        print(f"  {n:,} rows  |  {len(schema)} columns  |  {size / 1e9:,.2f} GB on disk\n")
        for row in schema:
            print(f"    {row[0]:<22} {row[1]}")
        print()
        return n
    finally:
        if own:
            con.close()


def stats(path, con=None, fmt=None, skip=0):
    """Per-column summary (min/max/nulls/approx-unique) via DuckDB SUMMARIZE."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        ensure_excel(con, path)
        _load_source_ext(con, fmt)
        src = _source(path, fmt=fmt, skip=skip)
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


def peek(path, n=20, con=None, fmt=None, skip=0):
    """A quick, zero-dependency look: first N rows as an aligned table,
    plus each column's type and null count (over the sample)."""
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        ensure_excel(con, path)
        _load_source_ext(con, fmt)
        src = _source(path, fmt=fmt, skip=skip)
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
        ensure_excel(con, path)
        p = _source(path)
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


# ------------------------------------------------------------- plot (ascii)

_NUMERIC_TYPES = ("INT", "DEC", "DOUBLE", "FLOAT", "REAL", "NUMERIC",
                  "HUGEINT", "BIGINT", "TINYINT", "SMALLINT", "UINT", "UBIGINT")


def _is_numeric_type(t) -> bool:
    return any(k in str(t).upper() for k in _NUMERIC_TYPES)


def _match_col(cols, name):
    for c in cols:
        if c.lower() == str(name).lower():
            return c
    raise ValueError(f"column '{name}' not found. columns: {', '.join(cols)}")


def _bar_glyphs():
    """Smooth unicode eighth-blocks when the console can encode them, else a
    plain ASCII '#' bar (so it never crashes a cp1252 Windows console)."""
    full, parts = "█", " ▏▎▍▌▋▊▉"
    try:
        enc = sys.stdout.encoding or "utf-8"
        (full + parts).encode(enc)
        return full, parts
    except (UnicodeEncodeError, LookupError, AttributeError, TypeError):
        return "#", ""


def _make_bar(v, maxv, width, full, parts):
    if maxv <= 0:
        return ""
    eighths = int(round(max(0.0, v / maxv) * width * 8))
    if v > 0 and eighths == 0:
        eighths = 1
    whole, rem = divmod(eighths, 8)
    bar = full * whole
    if parts and rem:
        bar += parts[rem]
    elif not parts and v > 0 and not bar:
        bar = full
    return bar


def _fmt_v(v):
    if v is None:
        return "0"
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def _num_edge(x):
    ax = abs(x)
    if ax != 0 and (ax < 0.01 or ax >= 1e7):
        return f"{x:.2e}"
    if float(x).is_integer():
        return f"{int(x):,}"
    return f"{x:,.2f}"


def _print_bars(title, data, width=48):
    """data = [(label, value), ...] already ordered. Prints an ASCII bar chart."""
    print("\n  " + title)
    if not data:
        print("  (no data)\n")
        return
    full, parts = _bar_glyphs()
    maxv = max((v for _, v in data), default=0) or 0
    lw = min(28, max((len(k) for k, _ in data), default=1))
    vw = max((len(_fmt_v(v)) for _, v in data), default=1)
    print()
    for k, v in data:
        label = k if len(k) <= lw else k[: lw - 1] + "."
        bar = _make_bar(v, maxv, width, full, parts)
        print(f"  {label.ljust(lw)}  {bar.ljust(width)}  {_fmt_v(v).rjust(vw)}")
    print()


def plot(path, column, by=None, agg=None, bins=20, top=20, width=48, con=None, fmt=None):
    """Draw a quick ASCII chart in the terminal - spot skew / dirty data fast.

      plot sales.csv amount              -> histogram (numeric) or top values (text)
      plot sales.csv amount --by city    -> bar chart of agg(amount) per city
    """
    own = con is None
    con = con or connect()
    try:
        ensure_remote(con, path)
        ensure_excel(con, path)
        _load_source_ext(con, fmt)
        src = _source(path, fmt=fmt)
        return plot_from(con, src, column, by=by, agg=agg, bins=bins, top=top, width=width)
    finally:
        if own:
            con.close()


def plot_from(con, src, column, by=None, agg=None, bins=20, top=20, width=48):
    """The plot engine over an already-resolved FROM source (a quoted path or a
    parenthesised subquery) - lets the interactive shell chart the live pipeline."""
    types = {r[0]: r[1] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
    col = _match_col(list(types), column)
    numeric = _is_numeric_type(types[col])

    if by:
        cat = _match_col(list(types), by)
        fn = str(agg or ("sum" if numeric else "count")).lower()
        fn = "avg" if fn == "mean" else fn
        if fn not in _AGGS:
            raise ValueError(f"--agg must be one of: {', '.join(sorted(_AGGS))}")
        expr = "count(*)" if fn == "count" else f"{fn}({_ident(col)})"
        rows = con.execute(
            f"SELECT CAST({_ident(cat)} AS VARCHAR) AS k, {expr} AS v FROM {src} "
            f"WHERE {_ident(cat)} IS NOT NULL GROUP BY 1 "
            f"ORDER BY v DESC NULLS LAST LIMIT {int(top)}"
        ).fetchall()
        title = f"{fn}({col}) by {cat}   (top {len(rows)})"
        _print_bars(title, [(_s(k), float(v or 0)) for k, v in rows], width)
        return len(rows)

    if numeric:
        lo, hi, n = con.execute(
            f"SELECT min({_ident(col)}), max({_ident(col)}), count({_ident(col)}) FROM {src}"
        ).fetchone()
        if not n or lo is None:
            print(f"\n  {col}: no numeric values to plot\n")
            return 0
        lo, hi, B = float(lo), float(hi), max(1, int(bins))
        if hi <= lo:
            _print_bars(f"{col}   ({n:,} rows, all = {_num_edge(lo)})",
                        [(f"{_num_edge(lo)}", float(n))], width)
            return 1
        bw = (hi - lo) / B
        raw = con.execute(
            f"SELECT LEAST({B - 1}, GREATEST(0, CAST(floor(({_ident(col)} - {lo}) / {bw}) AS BIGINT))) AS b, "
            f"count(*) AS c FROM {src} WHERE {_ident(col)} IS NOT NULL GROUP BY b"
        ).fetchall()
        counts = {int(b): int(c) for b, c in raw}
        data = [
            (f"[{_num_edge(lo + i * bw)}, {_num_edge(lo + (i + 1) * bw)})", float(counts.get(i, 0)))
            for i in range(B)
        ]
        _print_bars(f"{col}   histogram ({B} bins, {n:,} values)", data, width)
        return B

    # categorical column, no --by: value counts
    rows = con.execute(
        f"SELECT CAST({_ident(col)} AS VARCHAR) AS k, count(*) AS v FROM {src} "
        f"GROUP BY 1 ORDER BY v DESC LIMIT {int(top)}"
    ).fetchall()
    _print_bars(f"{col}   value counts (top {len(rows)})",
                [(_s(k), float(v)) for k, v in rows], width)
    return len(rows)


# ---------------------------------------------------------- messy-csv sniffer

def sniff_preamble(path, probe=25) -> int:
    """Best-effort: how many junk/preamble lines sit before the real CSV header
    (blank lines, or lines with a different delimiter-count than the data body)?
    Returns a small int suggestion (0 = looks clean). Local csv/text only."""
    if is_remote(path) or _ext(path) not in ("", ".csv", ".tsv", ".txt"):
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            lines = []
            for _ in range(probe):
                ln = f.readline()
                if not ln:
                    break
                lines.append(ln.rstrip("\r\n"))
    except OSError:
        return 0
    if len(lines) < 3:
        return 0

    import collections
    if _ext(path) == ".tsv":
        delim = "\t"
    else:
        body = lines[3:] or lines
        delim = max((",", ";", "\t", "|"), key=lambda d: sum(ln.count(d) for ln in body))
        if not sum(ln.count(delim) for ln in body):
            delim = ","
    counts = [ln.count(delim) for ln in lines]
    body_counts = [c for c in counts[min(len(counts) - 1, 3):] if c > 0]
    modal = collections.Counter(body_counts).most_common(1)
    if not modal:
        return 0
    mode = modal[0][0]

    skip = 0
    for i, ln in enumerate(lines[:-1]):
        if ln.strip() == "" or counts[i] != mode:
            skip += 1
        else:
            break
    return skip if 0 < skip <= min(10, len(lines) // 2) else 0


# ------------------------------------------------------------- combine / diff

def join(left, right, on, how="inner", out=None, con=None, quiet=False, disk_check=True):
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    try:
        ensure_remote(con, left, right, out)
        ensure_excel(con, left, right, out)
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
        record_history("join", left, out, n, time.time() - t0)
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
        record_history("partition", input_path, out_dir)
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
        ensure_excel(con, input_path, out)
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
        record_history("pivot", input_path, out, n, time.time() - t0)
        return n
    finally:
        if own:
            con.close()


def unpivot(input_path, cols, name="name", value="value", out=None, con=None,
            quiet=False, disk_check=True):
    """Reshape wide -> long: fold the named columns into two columns (a name
    column and a value column). The complement of pivot / a 'melt'."""
    own = con is None
    con = con or connect(progress=(not quiet) and _tty())
    try:
        ensure_remote(con, input_path, out)
        ensure_excel(con, input_path, out)
        collist = ", ".join(_ident(c) for c in _aslist(cols))
        q = (
            f"SELECT * FROM (SELECT * FROM {_source(input_path)}) _t "
            f"UNPIVOT ({_ident(value)} FOR {_ident(name)} IN ({collist}))"
        )
        t0 = time.time()
        _disk_check(con, [input_path], out, skip=not disk_check)
        n = _copy(con, q, out, _copy_opts(out if out != "-" else "out.csv"))
        if not quiet and out != "-":
            print(f"  done: {n:,} rows -> {out}  ({time.time() - t0:,.1f}s)")
        record_history("unpivot", input_path, out, n, time.time() - t0)
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
            ensure_excel(con, out)
            t0 = time.time()
            n = _copy(con, query, out, _copy_opts(out if out != "-" else "out.csv"))
            if not quiet and out != "-":
                print(f"  done: {n:,} rows -> {out}  ({time.time() - t0:,.1f}s)")
            record_history("sql", None, out, n, time.time() - t0)
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
        ensure_excel(con, input_path)
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
            fpath = os.path.join(out_dir, f"{name}.{ext}")
            dst = "'" + sql_path(fpath) + "'"
            row = con.execute(f"COPY (SELECT * FROM {src} WHERE {where}) TO {dst} {opts}").fetchone()
            n = row[0] if row else _count_file(con, fpath)
            total += n
            print(f"  {name}.{ext}: {n:,} rows")
        print(f"  done: {len(vals)} files, {total:,} rows -> {out_dir}")
        record_history("split", input_path, out_dir, total, extra={"files": len(vals)})
        return len(vals)
    finally:
        if own:
            con.close()


# ---------------------------------------------------------- scaffolding / API

def init(path="recipe.dq", input_path=None, con=None):
    """Write a starter .dq recipe. If input_path is given, its columns are read
    and pre-filled so you can just delete what you don't want."""
    if os.path.exists(path):
        raise ValueError(f"{path} already exists (refusing to overwrite)")
    inp = input_path or "data/input.csv"
    lines = [
        "# kenze recipe - edit the steps you want, delete the rest.",
        "# every step is the same word as a `kenze` command (see: kenze recipe)",
        "",
        f"input:  {inp}",
    ]
    if input_path:
        own = con is None
        con = con or connect()
        try:
            ensure_remote(con, input_path)
            cols = columns(con, _source(input_path))
        finally:
            if own:
                con.close()
        lines.append(f"# columns in {os.path.basename(input_path)}: {', '.join(cols)}")
        lines.append(f"keep:   [{', '.join(cols[:4])}]")
    else:
        lines.append("keep:   [col_a, col_b]")
    stem = os.path.splitext(os.path.basename(inp))[0]
    lines += [
        "# filter: amount > 0",
        "# types:  zip:VARCHAR",
        "# fillna: city:Unknown",
        "# dedup:  id",
        "# sample: 50000",
        f"output: {stem}_clean.csv",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  wrote starter recipe -> {path}\n  edit it, then run:  kenze run {path}")
    return path


def _frame(query, kind, con=None):
    own = con is None
    con = con or connect()
    try:
        rel = con.execute(query)
        if kind == "arrow":
            return rel.fetch_arrow_table()
        if kind == "polars":
            return rel.pl()
        return rel.df()
    finally:
        if own:
            con.close()


def to_arrow(query, con=None):
    """Run SQL and return the result as a pyarrow Table (needs `pip install kenze[arrow]`)."""
    return _frame(query, "arrow", con)


def to_polars(query, con=None):
    """Run SQL and return the result as a Polars DataFrame (needs `pip install kenze[polars]`)."""
    return _frame(query, "polars", con)


def to_df(query, con=None):
    """Run SQL and return the result as a pandas DataFrame (needs pandas)."""
    return _frame(query, "df", con)
