"""kenze interactive shell - a Claude-Code-style session for data prep.

Run `kenze` with no arguments (or `kenze shell`) and you land in a persistent,
colourful session:

    kenze > load big.parquet
    kenze > /            <- a live command menu pops up
    kenze > filter amount > 0
    kenze > keep <TAB>   <- TAB autofills the loaded file's real column names
    kenze > peek
    kenze > run clean.csv

Each step builds a live recipe with previews; `save clean.dq` / `eject` / `run`
graduate the session out to a file or raw SQL - no lock-in.

The pretty shell (colours, / menu, TAB autofill) uses `prompt_toolkit`, which ships
with kenze as a core dependency. On a terminal that can't be driven for a rich UI
(some minimal shells), a plain line-based REPL still works (just no colour/menu).
"""
from __future__ import annotations

import os
import re

from . import __version__
from .engine import connect
from .ops import (
    _clip,
    _ident,
    _load_source_ext,
    _s,
    build_query,
    check,
    columns,
    diff,
    eject,
    history,
    join,
    partition,
    pivot,
    plot_from,
    run_spec,
    run_sql,
    sniff_preamble,
    split,
    traintest,
    unpivot,
    validate,
)

# command name -> (group, one-line description).  this IS the / palette.
COMMANDS = {
    "load":   ("LOOK", "load a data file into the session"),
    "open":   ("LOOK", "open a saved .dq recipe into the session (view/edit/run)"),
    "peek":   ("LOOK", "preview the current data (first rows)"),
    "schema": ("LOOK", "show the current columns + types"),
    "count":  ("LOOK", "count rows in the current pipeline"),
    "stats":  ("LOOK", "per-column summary (min/max/nulls/unique)"),
    "plot":   ("LOOK", "quick ascii chart of a column (histogram / bar)"),
    "check":  ("LOOK", "integrity scan: readable? how many bad rows?"),
    "validate": ("LOOK", "check the file against a schema json"),
    "keep":   ("SHAPE", "keep only these columns"),
    "drop":   ("SHAPE", "remove these columns"),
    "filter": ("SHAPE", "keep rows matching a SQL condition"),
    "rename": ("SHAPE", "rename columns (old:new)"),
    "cast":   ("SHAPE", "cast a column's type (col:TYPE)"),
    "fillna": ("SHAPE", "replace nulls in a column (col:value)"),
    "mask":   ("SHAPE", "mask sensitive columns (one-way hash)"),
    "scale":  ("SHAPE", "scale a numeric column for ML (minmax / zscore)"),
    "bin":    ("SHAPE", "bucket a numeric column into N bins (adds col_bin)"),
    "encode": ("SHAPE", "label-encode a category column to integers (0-based)"),
    "onehot": ("SHAPE", "one-hot encode a category column to 0/1 columns"),
    "clip-outliers": ("SHAPE", "cap extreme values / winsorize (iqr / pct)"),
    "dedup":  ("SHAPE", "drop duplicate rows (cols, or all)"),
    "clip":   ("SHAPE", "keep rows inside a lat/lon bbox"),
    "sample": ("SHAPE", "keep N random rows"),
    "head":   ("SHAPE", "keep only the first N rows"),
    "join":   ("COMBINE", "join the loaded file with another on a key"),
    "diff":   ("COMBINE", "compare the loaded file with another (added/removed/changed)"),
    "pivot":  ("COMBINE", "reshape long -> wide"),
    "unpivot": ("COMBINE", "reshape wide -> long"),
    "split":  ("COMBINE", "split the loaded file into many by a column's values"),
    "partition": ("COMBINE", "hive-partition the loaded file (col=value/)"),
    "traintest": ("COMBINE", "split into train/test files (random or time-based)"),
    "assert": ("GUARD", "fail the run unless a condition holds (uses row_count)"),
    "assert-unique": ("GUARD", "fail the run if these column(s) have duplicates"),
    "assert-not-null": ("GUARD", "fail the run if these columns contain nulls"),
    "steps":  ("PIPE", "show the recipe built so far"),
    "undo":   ("PIPE", "remove the last step"),
    "reset":  ("PIPE", "clear all steps (keep the loaded file)"),
    "sql":    ("OUT", "run raw DuckDB SQL and print the result"),
    "eject":  ("OUT", "show the SQL/python for the pipeline (add a filename to save it)"),
    "dryrun": ("OUT", "show what `run` would write (schema), without writing"),
    "save":   ("OUT", "save the pipeline as a reusable .dq recipe"),
    "run":    ("OUT", "run the pipeline and write an output file"),
    "convert": ("OUT", "change file format (csv/parquet/json/xlsx/geojson)"),
    "pwd":    ("SHELL", "show the output folder (where run/save write)"),
    "cd":     ("SHELL", "change the output folder"),
    "set":    ("SHELL", "session settings: memory / threads / skip-bad / temp / disk-check"),
    "history": ("SHELL", "recent kenze runs (input -> output, rows, time)"),
    "recipe": ("SHELL", "show the .dq recipe format reference"),
    "help":   ("SHELL", "the guided command list"),
    "clear":  ("SHELL", "clear the screen"),
    "exit":   ("SHELL", "leave the shell"),
}
GROUPS = [("LOOK", "look at data"), ("SHAPE", "shape it"),
          ("COMBINE", "combine / reshape / split"), ("GUARD", "data-quality checks"),
          ("PIPE", "the pipeline"), ("OUT", "get it out"), ("SHELL", "shell")]
# commands whose arguments are (mostly) column names -> schema autocomplete
COLUMN_CMDS = {"keep", "drop", "filter", "rename", "cast", "fillna", "mask",
               "scale", "bin", "encode", "onehot", "clip-outliers", "dedup", "pivot",
               "unpivot", "split", "partition", "plot", "assert-unique", "assert-not-null"}
# commands whose first argument is a file path -> path autocomplete
FILE_CMDS = {"load", "open", "save", "run", "convert"}
# how a step maps into a recipe spec; the shell folds them in order
_STEP_KEYS = {
    "keep": "keep", "drop": "drop", "clip": "bbox",
    "dedup": "dedup", "sample": "sample", "head": "head",
}

# guided next-step hints: command -> (what to type next, example, needs an arg?,
# [optional keyword completions]). Drives the live bottom-toolbar hint + TAB.
CMD_GUIDE = {
    "load":    ("a file to load", "load data.csv", True, []),
    "open":    ("a recipe file", "open clean.dq", True, []),
    "filter":  ("a condition", "filter amount > 100", True, []),
    "keep":    ("columns to keep", "keep id, city", True, []),
    "drop":    ("columns to drop", "drop notes", True, []),
    "rename":  ("old:new", "rename amount:total", True, []),
    "cast":    ("col:TYPE", "cast id:VARCHAR", True, []),
    "fillna":  ("col:value", "fillna city:unknown", True, []),
    "mask":    ("columns to mask", "mask email, phone", True, []),
    "scale":   ("col:method", "scale age:zscore", True, []),
    "bin":     ("col:bins", "bin age:5", True, []),
    "encode":  ("a column", "encode city", True, []),
    "onehot":  ("a column", "onehot city", True, []),
    "dedup":   ("columns (or Enter for whole-row)", "dedup id", False, []),
    "sample":  ("how many rows", "sample 1000", True, []),
    "head":    ("how many rows", "head 100", True, []),
    "clip":    ("min_lon,min_lat,max_lon,max_lat", "clip 55,25,56,26", True, []),
    "plot":    ("a column", "plot amount by city", True, []),
    "sql":     ("a SQL query", "sql SELECT * FROM data LIMIT 5", True, []),
    "join":    ("a file + on <key>", "join other.csv on id", True, []),
    "run":     ("an output file", "run clean.csv", True, ["append", "errors", "log"]),
    "convert": ("an output file", "convert out.geojson", True, ["geom=", "lat=", "lon="]),
    "save":    ("a recipe file", "save clean.dq", True, []),
    "eject":   ("nothing (Enter to print), or a file", "eject out.sql", False, ["python"]),
    "set":     ("a setting", "set memory 4GB", True,
                ["memory", "threads", "temp", "disk-check", "skip-bad"]),
    "cd":      ("a folder", "cd outputs", True, []),
    "validate": ("a schema file", "validate schema.json", True, []),
    "diff":    ("another file + on <key>", "diff new.csv on id", True, []),
    "pivot":   ("on <col> values <col>", "pivot on month values sales", True, []),
    "unpivot": ("columns to fold", "unpivot jan,feb,mar", True, []),
    "split":   ("by <column>", "split by city", True, []),
    "partition": ("by <column>", "partition by year", True, []),
    "traintest": ("an output folder", "traintest split/ ratio 0.8", True, []),
    "assert":  ("a condition", "assert row_count > 0", True, []),
    "assert-unique":   ("column(s)", "assert-unique id", True, []),
    "assert-not-null": ("column(s)", "assert-not-null id", True, []),
    "clip-outliers": ("col:method", "clip-outliers amount:iqr", True, []),
}
# commands that run immediately - nothing more to type, just Enter
READY_ON_ENTER = {"peek", "schema", "count", "stats", "steps", "undo", "reset",
                  "pwd", "history", "help", "clear", "exit", "dryrun", "recipe", "check"}
# method / type keywords completed after a colon (cast id:VARCHAR, scale x:zscore)
_COL_METHODS = {
    "cast": ["VARCHAR", "INT", "BIGINT", "DOUBLE", "DATE", "TIMESTAMP", "BOOLEAN"],
    "scale": ["minmax", "zscore"],
    "clip-outliers": ["iqr", "pct"],
}


def _guide_hint(text, has_input):
    """What to type next for the current input line. Returns (kind, message):
    kind is 'start'/'flow'/'need'/'ready', message is the guidance text."""
    stripped = text.strip()
    if stripped.startswith("/"):
        stripped = stripped[1:].strip()
    if not stripped:
        if not has_input:
            return ("start", "load a file to begin    e.g.  load data.csv")
        return ("flow", "add a step (filter / keep / dedup ...) then  run out.csv"
                         "    -or-  convert out.geojson")
    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd in READY_ON_ENTER:
        return ("ready", "press Enter to run")
    g = CMD_GUIDE.get(cmd)
    if not g:
        return None
    label, eg, needs, opts = g
    if not arg and needs:
        return ("need", f"next: {label}    e.g.  {eg}")
    if opts:
        return ("ready", f"press Enter to run    (optional: {' '.join(opts)})")
    return ("ready", "press Enter to run")

# gradient-gold wordmark (figlet 'slant', pure ASCII) shown on entry
_WORDMARK = [
    "     __                       ",
    "    / /_____  ____  ____  ___ ",
    "   / //_/ _ \\/ __ \\/_  / / _ \\",
    "  / ,< /  __/ / / / / /_/  __/",
    " /_/|_|\\___/_/ /_/ /___/\\___/ ",
]
_WORD_COLORS = ["#ffe08a", "#ffd479", "#f0b429", "#d99e1f", "#c98a1a"]

_STYLE_DICT = {
    # inline chrome classes
    "brand":   "#f0b429 bold",
    "arrow":   "#c98a1a",
    "ok":      "#9ccc65",
    "warn":    "#ffb454",
    "err":     "#ff6b6b bold",
    "dim":     "#8a8a8a",
    "accent":  "#f0b429 bold",
    "accent2": "#ffd479",
    "link":    "#6cb6ff underline",
    "head":    "#ffd479 bold",
    "rule":    "#4a4a4a",
    "grp":     "#f0b429 bold",
    # the / command menu
    "completion-menu": "bg:#141414",
    "completion-menu.completion": "bg:#141414 #cfcfcf",
    "completion-menu.completion.current": "bg:#f0b429 #101010 bold",
    "completion-menu.meta.completion": "bg:#1c1c1c #8a8a8a italic",
    "completion-menu.meta.completion.current": "bg:#c98a1a #101010",
    "scrollbar.background": "bg:#2a2a2a",
    "scrollbar.button": "bg:#f0b429",
    # bottom toolbar
    "bottom-toolbar": "bg:#f0b429 #101010",
    "tb-key": "bg:#f0b429 #101010 bold",
    "tb-dim": "bg:#f0b429 #6b5200",
}

# set up once when the pretty shell starts (see run_shell)
_RICH = False
_STYLE = None
_PF = None
_FT = None


def _say(text="", cls=""):
    if _RICH and _PF is not None:
        _PF(_FT([(("class:" + cls) if cls else "", text)]), style=_STYLE)
    else:
        print(text)


def _say_parts(parts):
    """parts = [(class, text), ...] -> one coloured line."""
    if _RICH and _PF is not None:
        _PF(_FT([(("class:" + c) if c else "", t) for c, t in parts]), style=_STYLE)
    else:
        print("".join(t for _, t in parts))


def _split_args(s):
    """Whitespace-split respecting "..." / '...' quotes, keeping backslashes
    (so Windows paths with spaces survive: `join "Feb 10.csv" id out.csv`)."""
    out, cur, q, seen = [], "", None, False
    for ch in s:
        if q:
            if ch == q:
                q = None
            else:
                cur += ch
        elif ch in "\"'":
            q, seen = ch, True
        elif ch.isspace():
            if cur or seen:
                out.append(cur)
            cur, seen = "", False
        else:
            cur += ch
    if cur or seen:
        out.append(cur)
    return out


class ShellState:
    """Holds the one DuckDB connection + the recipe being built live."""

    def __init__(self):
        self.input = None
        self.cols = []           # current (post-transform) columns, for autocomplete
        self.steps = []          # ordered [(cmd, arg), ...]
        self.auto_preview = True
        # session settings (mirrors the CLI global flags)
        self.mem_gb = None       # None = auto-size to free RAM
        self.threads = None      # None = all cores
        self.skip_bad = False    # ignore malformed CSV rows on read
        self.skip = 0            # preamble rows to skip on the loaded csv
        self.source_format = None  # 'delta' | 'iceberg' for the loaded file
        self.temp_dir = None     # disk-spill location (None = system temp)
        self.disk_check = True   # pre-flight free-space check before a write
        self.con = None
        self.reconnect()

    def reconnect(self):
        """(Re)open the DuckDB connection with the current memory/thread/temp
        settings. A native progress bar shows on heavy ops in a real terminal."""
        import sys
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
        self.con = connect(memory_limit_gb=self.mem_gb, threads=self.threads,
                           temp_dir=self.temp_dir, progress=sys.stderr.isatty())

    # ---- building the live recipe -------------------------------------
    def build_spec(self, output=None):
        spec = {}
        if self.input:
            spec["input"] = self.input
        if self.skip_bad:
            spec["skip_bad_lines"] = True
        if self.skip:
            spec["skip"] = self.skip
        if self.source_format:
            spec["source_format"] = self.source_format
        filters, casts, fills, renames = [], [], [], []
        asserts, auniq, anotnull = [], [], []
        scales, binspecs, encodes, onehots, clipouts = [], [], [], [], []
        for cmd, arg in self.steps:
            if cmd == "filter":
                filters.append(arg)
            elif cmd == "cast":
                casts.append(arg)
            elif cmd == "fillna":
                fills.append(arg)
            elif cmd == "rename":
                renames.append(arg)
            elif cmd == "scale":
                p = arg.split()
                scales.append(f"{p[0]}:{p[1] if len(p) > 1 else 'minmax'}")
            elif cmd == "bin":
                p = arg.split()
                nb = p[1] if len(p) > 1 else "5"
                mth = p[2] if len(p) > 2 else "uniform"
                binspecs.append(f"{p[0]}:{nb}:{mth}")
            elif cmd == "encode":
                encodes.append(arg.split()[0])
            elif cmd == "onehot":
                p = arg.split()
                onehots.append(p[0] if len(p) < 2 else f"{p[0]}:{p[1]}")
            elif cmd == "clip-outliers":
                p = arg.split()
                clipouts.append(p[0] if len(p) < 2 else f"{p[0]}:{p[1]}")
            elif cmd == "mask":
                spec["mask"] = arg
                spec.setdefault("mask_method", "hash")
            elif cmd == "assert":
                asserts.append(arg)
            elif cmd == "assert-unique":
                auniq.append(arg)
            elif cmd == "assert-not-null":
                anotnull.append(arg)
            elif cmd in _STEP_KEYS:
                spec[_STEP_KEYS[cmd]] = arg
        if filters:
            spec["filter"] = " AND ".join(f"({f})" for f in filters)
        if casts:
            spec["types"] = ", ".join(casts)
        if fills:
            spec["fillna"] = ", ".join(fills)
        if renames:
            spec["rename"] = ", ".join(renames)
        if scales:
            spec["scale"] = ", ".join(scales)
        if binspecs:
            spec["bin"] = ", ".join(binspecs)
        if encodes:
            spec["encode"] = ", ".join(encodes)
        if onehots:
            spec["onehot"] = ", ".join(onehots)
        if clipouts:
            spec["clip_outliers"] = ", ".join(clipouts)
        if asserts:
            spec["assert"] = asserts
        if auniq:
            spec["assert_unique"] = auniq
        if anotnull:
            spec["assert_not_null"] = anotnull
        if output:
            spec["output"] = output
        return spec

    def current_query(self):
        return build_query(self.con, self.build_spec())

    def refresh_cols(self):
        try:
            if self.input:
                self.cols = columns(self.con, f"({self.current_query()})")
        except Exception:
            pass  # keep the old columns if a half-typed step doesn't build


# ------------------------------------------------------------- handlers

def _need_input(st):
    if not st.input:
        _say("  no data loaded yet - try:  load <file>", "warn")
        return True
    return False


def _print_table(st, query, n=8):
    rows = st.con.execute(f"SELECT * FROM ({query}) _p LIMIT {int(n)}").fetchall()
    names = [d[0] for d in st.con.description]
    cells = [[_s(v) for v in r] for r in rows]
    widths = []
    for i, name in enumerate(names):
        w = len(name)
        for row in cells:
            w = max(w, len(row[i]))
        widths.append(min(w, 40))

    def line(vals):
        return "  " + "  ".join(_clip(vals[i], widths[i]).ljust(widths[i])
                                for i in range(len(vals)))

    print()
    _say(line(names), "head")                                   # gold header
    _say("  " + "  ".join("-" * widths[i] for i in range(len(names))), "rule")
    for row in cells:
        print(line(row))                                        # data stays clean
    _say(f"\n  ({len(rows)} row preview)\n", "dim")


def h_load(st, arg):
    if not arg:
        _say("  usage: load <file>    (optional:  load messy.csv skip 3   |   load t as delta)", "warn")
        return
    raw = arg.strip()
    fmt = None                               # load <path> as delta|iceberg
    for f in ("delta", "iceberg"):
        if raw.lower().endswith(" as " + f):
            fmt, raw = f, raw[: -(4 + len(f))].strip()
    skip = 0                                 # load <path> skip N  (drop preamble)
    m = re.search(r"\s+skip\s+(\d+)\s*$", raw, re.IGNORECASE)
    if m:
        skip, raw = int(m.group(1)), raw[: m.start()].strip()
    path = raw.strip('"').strip("'")

    guess = 0                                # sniff obvious junk preamble
    if not skip and not fmt:
        try:
            guess = sniff_preamble(path)
        except Exception:
            guess = 0

    def _read(skip_n):
        probe = {"input": path, "skip_bad_lines": st.skip_bad,
                 "source_format": fmt, "skip": skip_n}
        return columns(st.con, f"({build_query(st.con, probe)})")

    try:                                     # read the schema first, so a
        from .engine import ensure_remote    # missing/unreadable file fails loudly
        ensure_remote(st.con, path)
        _load_source_ext(st.con, fmt)        # delta/iceberg extension on demand
        try:
            cols = _read(skip)
            if not skip and guess:           # loaded, but preamble may be polluting it
                _say(f"  heads-up: {guess} preamble line(s) detected - if the columns below "
                     f"look wrong, reload with  `load {os.path.basename(path)} skip {guess}`", "warn")
        except Exception:
            if not skip and guess:           # smart-import: auto-skip the junk header
                cols = _read(guess)
                skip = guess
                _say(f"  detected + auto-skipped {guess} preamble line(s)  "
                     f"(reload with `skip 0` to keep them)", "warn")
            else:
                raise
    except Exception as e:
        shown = os.path.basename(path.rstrip("/\\")) or path
        _say(f"  Error: couldn't load {shown}  ({e})", "err")
        return
    st.input, st.cols, st.steps = path, cols, []
    st.source_format, st.skip = fmt, skip
    ncols = len(cols)
    extra = f", skipped {skip} preamble" if skip else ""
    _say(f"\n  loaded  {os.path.basename(path)}   ({ncols} columns{extra})", "ok")
    _say("  columns:  " + ", ".join(cols[:12]) + (" ..." if ncols > 12 else ""), "dim")
    _say("  tip: build a pipeline - filter / keep / dedup ... each previews live\n", "dim")


def h_peek(st, arg):
    if _need_input(st):
        return
    s = arg.strip()
    if s and not s.isdigit():
        _say(f"  peek takes a row count, e.g. `peek 20` - ignoring '{s}', showing 10", "warn")
    _print_table(st, st.current_query(), int(s) if s.isdigit() else 10)


def h_schema(st, arg):
    if _need_input(st):
        return
    rows = st.con.execute(f"DESCRIBE {st.current_query()}").fetchall()
    print()
    for r in rows:
        _say_parts([("accent2", f"    {r[0]:<24}"), ("dim", str(r[1]))])
    print()


def h_count(st, arg):
    if _need_input(st):
        return
    n = st.con.execute(f"SELECT count(*) FROM ({st.current_query()}) _c").fetchone()[0]
    _say(f"\n  {n:,} rows\n", "accent")


def h_stats(st, arg):
    if _need_input(st):
        return
    q = st.current_query()
    rows = st.con.execute(f"SUMMARIZE {q}").fetchall()
    cols = [d[0] for d in st.con.description]
    show = [c for c in ("column_name", "column_type", "min", "max",
                        "approx_unique", "null_percentage") if c in cols]
    idx = [cols.index(c) for c in show]
    widths = [max(len(show[j]), *(len(_s(r[idx[j]])) for r in rows))
              for j in range(len(show))]
    print()
    _say("  " + "  ".join(show[j].ljust(widths[j]) for j in range(len(show))), "head")
    _say("  " + "  ".join("-" * widths[j] for j in range(len(show))), "rule")
    for r in rows:
        print("  " + "  ".join(_s(r[idx[j]]).ljust(widths[j]) for j in range(len(show))))
    print()


_PLOT_KEYS = ("by", "agg", "bins", "top", "width")
_PLOT_NUM = ("bins", "top", "width")


def h_plot(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if not a:
        _say("  usage: plot <column> [by <cat>] [agg sum|count|avg|min|max] [bins N] [top N]", "warn")
        _say("  e.g.   plot amount by city   |   plot amount city   |   plot amount bins 15", "dim")
        return
    column = a[0]
    opts = {"by": None, "agg": None, "bins": 20, "top": 20, "width": 48}
    unknown = []
    i = 1
    while i < len(a):
        key = a[i].lower()
        if key in _PLOT_KEYS:
            if i + 1 >= len(a):
                _say(f"  '{key}' needs a value (e.g. {key} ...) - ignoring it", "warn")
                break
            val = a[i + 1]
            if key in _PLOT_NUM:
                try:
                    opts[key] = int(val)
                except ValueError:
                    _say(f"  {key} must be a whole number, not '{val}' - using {opts[key]}", "warn")
            else:
                opts[key] = val
            i += 2
        elif opts["by"] is None:
            opts["by"] = a[i]          # a bare second column = the category (implicit `by`)
            i += 1
        else:
            unknown.append(a[i])
            i += 1
    if unknown:
        _say(f"  ignored: {', '.join(unknown)}   (usage: plot <col> [by <cat>] "
             f"[agg sum|count|avg|min|max] [bins N] [top N])", "warn")
    plot_from(st.con, f"({st.current_query()})", column, by=opts["by"], agg=opts["agg"],
              bins=opts["bins"], top=opts["top"], width=opts["width"])


def h_history(st, arg):
    s = arg.strip()
    if s and not s.isdigit():
        _say(f"  history takes a count, e.g. `history 50` - ignoring '{s}', showing 20", "warn")
    history(n=int(s) if s.isdigit() else 20)


_FILTER_OPS = ("!=", "<>", ">=", "<=", "==", "=", ">", "<")


def _looks_ready(v):
    """A value that's already valid SQL as-is: a quoted string or a number."""
    v = v.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        return True
    try:
        float(v)
        return True
    except ValueError:
        return False


def _repair_filter(cols, arg):
    """Turn a non-SQL filter (`status active`, `city = new york`) into valid SQL
    (`status = 'active'`), but ONLY for the simple <column> [op] <value> shape - so
    a non-SQL user's natural attempt works. Returns None if it doesn't fit."""
    parts = arg.strip().split(None, 1)
    if not parts:
        return None
    col = parts[0].strip('"').strip("'")
    match = [c for c in cols if c.lower() == col.lower()]
    if not match:                       # first word isn't a column -> leave it alone
        return None
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not rest:
        return None
    op = "="
    for o in _FILTER_OPS:               # an explicit operator?  (status = active)
        if rest.startswith(o):
            op, rest = ("=" if o == "==" else o), rest[len(o):].strip()
            break
    if not rest:
        return None
    value = rest if _looks_ready(rest) else "'" + rest.replace("'", "''") + "'"
    return f"{_ident(match[0])} {op} {value}"


def _run_step(st):
    """Count rows for the current pipeline (validates the last step builds)."""
    st.refresh_cols()
    return st.con.execute(f"SELECT count(*) FROM ({st.current_query()}) _c").fetchone()[0]


def _add_step(st, cmd, arg, preview=True):
    if _need_input(st):
        return
    if not arg and cmd not in ("dedup",):
        _say(f"  usage: {cmd} <...>", "warn")
        return
    st.steps.append((cmd, arg or "all"))
    try:
        rows = _run_step(st)
    except Exception as e:
        st.steps.pop()          # bad step: roll it back, no harm done
        # friendly filter: if a non-SQL condition failed, try to repair it
        if cmd == "filter":
            fixed = _repair_filter(st.cols, arg)
            if fixed and fixed != arg.strip():
                st.steps.append(("filter", fixed))
                try:
                    rows = _run_step(st)
                    _say_parts([("ok", f"  + filter {fixed}"),
                                ("dim", f"    (read `{arg}` as text)  -> {rows:,} rows")])
                    if preview and st.auto_preview:
                        _print_table(st, st.current_query(), 6)
                    return
                except Exception:
                    st.steps.pop()      # the repair didn't work either
            _say(f"  Error: {e}", "err")
            _say("  hint: text needs single quotes, use = to compare  ->  "
                 "filter city = 'London'   (numbers: age > 30)", "dim")
            return
        _say(f"  Error: {e}", "err")
        return
    _say_parts([("ok", f"  + {cmd} {arg}"), ("dim", f"    -> {rows:,} rows")])
    if preview and st.auto_preview:
        _print_table(st, st.current_query(), 6)


def h_steps(st, arg):
    if not st.input:
        _say("  (nothing loaded)", "dim")
        return
    _say_parts([("dim", "\n  input:  "), ("accent2", st.input)])
    if not st.steps:
        _say("  (no steps yet - try `filter ...` or `keep ...`)", "dim")
    for i, (cmd, a) in enumerate(st.steps, 1):
        _say_parts([("accent", f"  {i:>2}. "), ("brand", cmd), ("", f" {a}")])
    print()


def h_undo(st, arg):
    if not st.steps:
        _say("  nothing to undo", "dim")
        return
    cmd, a = st.steps.pop()
    st.refresh_cols()
    _say(f"  undone:  {cmd} {a}", "warn")


def h_reset(st, arg):
    st.steps = []
    st.refresh_cols()
    _say("  steps cleared (file still loaded)", "warn")


def h_sql(st, arg):
    if not arg.strip():
        _say("  usage: sql SELECT ...", "warn")
        return
    run_sql(arg, con=st.con, quiet=True)


def h_eject(st, arg):
    if _need_input(st):
        return
    # shell forms:
    #   eject                      -> print the SQL
    #   eject python               -> print a runnable python script
    #   eject out.sql / out.py     -> WRITE it to that file (format from the extension)
    #   eject python out.py        -> WRITE python to out.py
    # forgiving of `--to python`, `py`, `--to=python`; warn on anything else
    # (a `.dq` recipe or junk) instead of silently doing the wrong thing.
    tokens = arg.replace("--to=", " ").replace("--to", " ").split()
    to = None
    target = None
    unknown = []
    for t in tokens:
        low = t.lower()
        if low == "sql":
            to = "sql"
        elif low in ("python", "py"):
            to = "python"
        elif low.endswith((".sql", ".py", ".txt")):
            target = t
        else:
            unknown.append(t)
    if unknown:
        _say("  usage: eject  |  eject python  |  eject out.sql  |  eject out.py "
             "  (add a filename to save it)", "warn")
        _say(f"  don't understand '{' '.join(unknown)}' - the `recipe.dq --to python` "
             f"form is for the terminal, not the shell", "dim")
        return
    if to is None:  # infer format from the file extension, else default to SQL
        to = "python" if (target and target.lower().endswith(".py")) else "sql"
    code = eject(st.build_spec(), to=to)
    if target:
        path = os.path.abspath(target)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code + "\n")
        except OSError as e:
            _say(f"  couldn't write {path}: {e}", "warn")
            return
        _say_parts([("ok", f"  ejected {to} -> "), ("accent2", path)])
        return
    print()
    _say(code, "dim")
    print()


def _spec_to_recipe(spec):
    order = ["input", "keep", "drop", "filter", "bbox", "types", "fillna",
             "mask", "mask_method", "rename", "scale", "bin", "encode", "onehot",
             "clip_outliers", "dedup", "sample", "head",
             "assert", "assert_unique", "assert_not_null", "output"]
    lines = ["# kenze recipe - generated from an interactive session"]
    for k in order:
        if k not in spec:
            continue
        v = spec[k]
        if k in ("assert", "assert_unique", "assert_not_null") and isinstance(v, list):
            for item in v:                      # one line per assertion
                lines.append(f"{k}: {item}")
            continue
        if k in ("keep", "drop") and isinstance(v, str):
            v = "[" + ", ".join(x.strip() for x in v.split(",")) + "]"
        lines.append(f"{k}: {v}")
    return "\n".join(lines) + "\n"


def h_save(st, arg):
    if _need_input(st):
        return
    path = os.path.abspath((arg.strip() or "recipe.dq").strip('"').strip("'"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    spec = st.build_spec(output="out.csv")  # placeholder output, editable
    with open(path, "w", encoding="utf-8") as f:
        f.write(_spec_to_recipe(spec))
    _say(f"  saved recipe -> {path}", "ok")
    _say(f"  (re-run later:  kenze run \"{path}\")", "dim")


def h_run(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if not a:
        _say("  usage: run <name.csv|parquet|json>  [append] [errors <file>] [log <file>]", "warn")
        _say("  writes to the current output folder - see `pwd` / `cd`", "dim")
        return
    out = _out(a[0])
    append, errors, log, i = False, None, None, 1
    while i < len(a):
        t = a[i].lower()
        if t == "append":
            append, i = True, i + 1
        elif t == "errors" and i + 1 < len(a):
            errors, i = _out(a[i + 1]), i + 2
        elif t == "log" and i + 1 < len(a):
            log, i = _out(a[i + 1]), i + 2
        else:
            _say(f"  ignoring unknown option: {a[i]}", "warn")
            i += 1
    spec = st.build_spec(output=out)
    if append:
        spec["append"] = True
    if errors:
        spec["errors"] = errors
    _say(f"  running the pipeline -> {out}", "accent")
    run_spec(spec, con=st.con, quiet=False, disk_check=st.disk_check, log=log)


def h_convert(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if not a:
        _say("  usage: convert <output.csv|parquet|json|xlsx|geojson>", "warn")
        _say("  the loaded file is written to that name (format from the extension)", "dim")
        _say("  GeoJSON: lat/lon auto-detected, or  convert out.geojson geom=<column>", "dim")
        return
    # the file is already loaded, so convert takes only the OUTPUT - catch the
    # terminal form `convert input -o output` instead of silently mis-using it.
    if any(t.lower() in ("-o", "--output") for t in a):
        _say("  in the shell the file is already loaded - convert takes just the OUTPUT:", "warn")
        _say("      convert out.geojson          (no input path, no -o)", "dim")
        return
    out = _out(a[0])
    # never overwrite the file you loaded
    if st.input and os.path.abspath(out) == os.path.abspath(st.input):
        _say(f"  that would overwrite the file you loaded ({os.path.basename(st.input)}).", "warn")
        _say("  give a different output name, e.g.  convert out.geojson", "dim")
        return
    spec = st.build_spec(output=out)
    for t in a[1:]:
        low = t.lower()
        if low.startswith("lat="):
            spec["geo_lat"] = t.split("=", 1)[1]
        elif low.startswith("lon="):
            spec["geo_lon"] = t.split("=", 1)[1]
        elif low.startswith("geom="):
            spec["geo_wkt"] = t.split("=", 1)[1]
        else:
            _say(f"  ignoring unknown option: {t}  (GeoJSON uses lat=/lon=/geom=)", "warn")
    _say(f"  converting -> {out}", "accent")
    run_spec(spec, con=st.con, quiet=False, disk_check=st.disk_check)


def h_pwd(st, arg):
    _say(f"  output folder:  {os.getcwd()}", "accent2")
    _say("  files from `run` / `save` land here (or give a full path)", "dim")


def h_cd(st, arg):
    target = arg.strip().strip('"').strip("'")
    if not target:
        _say(f"  output folder:  {os.getcwd()}", "accent2")
        return
    try:
        os.chdir(os.path.expanduser(target))
    except OSError as e:
        _say(f"  Error: {e}", "err")
        return
    _say(f"  output folder -> {os.getcwd()}", "ok")


# ---- combine / reshape / fan-out (operate on the LOADED file) -------

def _pending_note(st):
    if st.steps:
        _say(f"  note: this uses the loaded file, not your {len(st.steps)} pending "
             "step(s) - `run`/`save` first to apply them", "dim")


def _out(p):
    p = os.path.abspath(p)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    return p


def h_check(st, arg):
    a = _split_args(arg)
    path = a[0] if a else st.input
    if not path:
        _say("  usage: check <file>   (or load a file first)", "warn")
        return
    check(path, con=st.con)


def h_validate(st, arg):
    a = _split_args(arg)
    if not a:
        _say("  usage: validate <schema.json> [file]   (file defaults to the loaded one)", "warn")
        return
    schema = a[0]
    path = a[1] if len(a) > 1 else st.input
    if not path:
        _say("  no file loaded - pass one: validate <schema.json> <file>", "warn")
        return
    validate(path, schema, con=st.con)


def _warn_extra(a, used, cmd):
    """Flag positional args beyond what a command consumes (don't silently drop)."""
    if len(a) > used:
        _say(f"  ignored extra: {', '.join(a[used:])}   (see `help` -> {cmd})", "warn")


def h_join(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if len(a) < 3:
        _say("  usage: join <right_file> <key> <out_file> [inner|left|right|full]", "warn")
        _say("  e.g.   join orders.csv customer_id joined.csv left", "dim")
        return
    right, key, out = a[0], a[1], _out(a[2])
    how = a[3] if len(a) > 3 else "inner"
    _warn_extra(a, 4, "join")
    _pending_note(st)
    _say(f"  join {os.path.basename(st.input)} + {os.path.basename(right)} on {key} ({how})", "accent")
    join(st.input, right, key, how=how, out=out, con=st.con)


def h_diff(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if len(a) < 2:
        _say("  usage: diff <other_file> <key> [out_file]", "warn")
        _say("  e.g.   diff yesterday.csv id   (add an out file to write the changed keys)", "dim")
        return
    other, key = a[0], a[1]
    out = _out(a[2]) if len(a) > 2 else None
    _warn_extra(a, 3, "diff")
    _pending_note(st)
    diff(st.input, other, key, out=out, con=st.con)


def h_pivot(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if len(a) < 3:
        _say("  usage: pivot <on_col> <values_col> <out_file> [sum|count|avg|min|max]", "warn")
        _say("  e.g.   pivot month sales wide.csv sum", "dim")
        return
    on, values, out = a[0], a[1], _out(a[2])
    agg = a[3] if len(a) > 3 else "sum"
    _warn_extra(a, 4, "pivot")
    _pending_note(st)
    pivot(st.input, on, values, agg=agg, out=out, con=st.con)


def h_unpivot(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if len(a) < 2:
        _say("  usage: unpivot <cols> <out_file>   (cols comma-separated)", "warn")
        _say("  e.g.   unpivot jan,feb,mar long.csv", "dim")
        return
    cols, out = a[0], _out(a[1])
    _warn_extra(a, 2, "unpivot")
    _pending_note(st)
    unpivot(st.input, cols, out=out, con=st.con)


def h_split(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if len(a) < 2:
        _say("  usage: split <by_col> <out_dir> [csv|parquet|json]", "warn")
        _say("  e.g.   split city cities/", "dim")
        return
    by, out_dir = a[0], os.path.abspath(a[1])
    fmt = a[2] if len(a) > 2 else "csv"
    _warn_extra(a, 3, "split")
    _pending_note(st)
    split(st.input, by, out_dir, fmt=fmt, con=st.con)


def h_partition(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if len(a) < 2:
        _say("  usage: partition <by_col(s)> <out_dir> [parquet|csv]", "warn")
        _say("  e.g.   partition year,month data/", "dim")
        return
    by, out_dir = a[0], os.path.abspath(a[1])
    fmt = a[2] if len(a) > 2 else "parquet"
    _warn_extra(a, 3, "partition")
    _pending_note(st)
    partition(st.input, by, out_dir, fmt=fmt, con=st.con, quiet=False)


def h_traintest(st, arg):
    if _need_input(st):
        return
    a = _split_args(arg)
    if not a:
        _say("  usage: traintest <out_dir> [ratio 0.8] [seed 42] [csv|parquet]", "warn")
        _say("  time-based:  traintest <out_dir> by order_date before 2026-01-01", "dim")
        return
    out_dir = os.path.abspath(a[0])
    ratio, seed, by, before, fmt = 0.8, 42, None, None, "parquet"
    i = 1
    while i < len(a):
        t = a[i].lower()
        if t == "ratio" and i + 1 < len(a):
            try:
                ratio = float(a[i + 1])
            except ValueError:
                _say(f"  ratio must be a number, got '{a[i + 1]}' - using 0.8", "warn")
            i += 2
        elif t == "seed" and i + 1 < len(a):
            try:
                seed = int(a[i + 1])
            except ValueError:
                _say(f"  seed must be a whole number, got '{a[i + 1]}' - using 42", "warn")
            i += 2
        elif t == "by" and i + 1 < len(a):
            by, i = a[i + 1], i + 2
        elif t == "before" and i + 1 < len(a):
            before, i = a[i + 1], i + 2
        elif t in ("csv", "parquet", "json"):
            fmt, i = t, i + 1
        else:
            _say(f"  ignoring: {a[i]}", "warn")
            i += 1
    _pending_note(st)
    traintest(st.input, out_dir, ratio=ratio, seed=seed, by=by, before=before,
              fmt=fmt, con=st.con, quiet=False)


# ---- data-quality guards (checked before a `run` write) ------------

_ASSERT_USAGE = {
    "assert": "assert <condition>        e.g. assert row_count > 0",
    "assert-unique": "assert-unique <cols>      e.g. assert-unique id",
    "assert-not-null": "assert-not-null <cols>    e.g. assert-not-null id, email",
}


def _add_assert(st, cmd, arg):
    if _need_input(st):
        return
    if not arg.strip():
        _say("  usage: " + _ASSERT_USAGE[cmd], "warn")
        return
    st.steps.append((cmd, arg.strip()))
    _say_parts([("ok", f"  + {cmd} {arg.strip()}"),
                ("dim", "    (checked before writing on `run`)")])


# ---- open / run a saved recipe, and the recipe reference -----------

def _multi(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _spec_to_steps(spec):
    def j(v):
        return v if isinstance(v, str) else ", ".join(str(x) for x in v)
    steps = []
    for key, cmd in (("keep", "keep"), ("drop", "drop"), ("filter", "filter"),
                     ("bbox", "clip"), ("types", "cast"), ("fillna", "fillna"),
                     ("mask", "mask"), ("rename", "rename"), ("dedup", "dedup"),
                     ("sample", "sample"), ("head", "head")):
        if spec.get(key):
            steps.append((cmd, j(spec[key])))
    for key in ("scale", "bin", "encode", "onehot"):   # 'col:method' list -> one step each
        if spec.get(key):
            for item in str(spec[key]).split(","):
                item = item.strip()
                if item:
                    steps.append((key, item.replace(":", " ")))
    if spec.get("clip_outliers"):        # spec key differs from the command name
        for item in str(spec["clip_outliers"]).split(","):
            item = item.strip()
            if item:
                steps.append(("clip-outliers", item.replace(":", " ")))
    for a in _multi(spec.get("assert")):
        steps.append(("assert", a))
    for a in _multi(spec.get("assert_unique")):
        steps.append(("assert-unique", a))
    for a in _multi(spec.get("assert_not_null")):
        steps.append(("assert-not-null", a))
    return steps


def h_open(st, arg):
    path = arg.strip().strip('"').strip("'")
    if not path:
        _say("  usage: open <recipe.dq>", "warn")
        return
    from .recipe import parse as parse_recipe
    try:
        with open(path, encoding="utf-8") as f:
            spec = parse_recipe(f.read())
    except Exception as e:
        _say(f"  Error: couldn't open {os.path.basename(path)}  ({e})", "err")
        return
    inp = spec.get("input")
    try:
        from .engine import ensure_remote
        ensure_remote(st.con, inp)
        cols = columns(st.con, f"({build_query(st.con, {'input': inp})})")
    except Exception as e:
        _say(f"  Error: the recipe's input didn't load  ({e})", "err")
        return
    st.input, st.cols, st.source_format = inp, cols, None
    st.steps = _spec_to_steps(spec)
    st.refresh_cols()
    _say(f"\n  opened  {os.path.basename(path)}   "
         f"({len(st.steps)} steps on {os.path.basename(inp)})", "ok")
    _say("  see `steps`, tweak with `undo` or add more, then `run <file>`\n", "dim")


def h_recipe(st, arg):
    from .recipe import REFERENCE
    print("\n" + REFERENCE)


def h_dryrun(st, arg):
    if _need_input(st):
        return
    q = st.current_query()
    rows = st.con.execute(f"DESCRIBE {q}").fetchall()
    _say(f"  dry run - `run <file>` would write {len(rows)} columns:", "accent")
    for r in rows:
        _say_parts([("accent2", f"    {r[0]:<24}"), ("dim", str(r[1]))])
    _say("  (see the exact SQL with `eject`)\n", "dim")


def h_set(st, arg):
    a = arg.split()
    if not a:
        mem = f"{st.mem_gb:g} GB" if st.mem_gb else "auto"
        thr = str(st.threads) if st.threads else "auto (all cores)"
        _say("  settings:", "head")
        _say_parts([("accent2", "    memory      "), ("", mem)])
        _say_parts([("accent2", "    threads     "), ("", thr)])
        _say_parts([("accent2", "    skip-bad    "), ("", "on" if st.skip_bad else "off")])
        _say_parts([("accent2", "    temp        "), ("", st.temp_dir or "auto (system temp)")])
        _say_parts([("accent2", "    disk-check  "), ("", "on" if st.disk_check else "off")])
        _say("  change with:  set memory 8 | set threads 4 | set skip-bad on"
             " | set temp D:\\spill | set disk-check off", "dim")
        return
    key, val = a[0].lower(), (a[1] if len(a) > 1 else "")
    try:
        if key == "memory":
            st.mem_gb = None if val.lower() in ("", "auto") else float(val)
            st.reconnect()
            _say(f"  memory -> {'auto' if not st.mem_gb else f'{st.mem_gb:g} GB'}", "ok")
        elif key == "threads":
            st.threads = None if val.lower() in ("", "auto") else int(val)
            st.reconnect()
            _say(f"  threads -> {st.threads or 'auto'}", "ok")
        elif key in ("skip-bad", "skipbad", "skip_bad"):
            st.skip_bad = val.lower() in ("on", "true", "1", "yes")
            _say(f"  skip-bad -> {'on' if st.skip_bad else 'off'}", "ok")
        elif key in ("temp", "temp-dir", "tempdir"):
            st.temp_dir = val or None
            st.reconnect()
            _say(f"  temp -> {st.temp_dir or 'auto'}", "ok")
        elif key in ("disk-check", "diskcheck", "disk_check"):
            st.disk_check = val.lower() in ("on", "true", "1", "yes")
            _say(f"  disk-check -> {'on' if st.disk_check else 'off'}", "ok")
        else:
            _say("  set what? memory | threads | skip-bad | temp | disk-check", "warn")
    except ValueError:
        _say(f"  Error: '{val}' is not a valid number", "err")


def h_help(st, arg):
    print()
    _say("  kenze commands   (type a command, or / for the live menu)", "head")
    for gid, glabel in GROUPS:
        _say_parts([("grp", f"\n  {glabel.upper()}")])
        for name, (grp, desc) in COMMANDS.items():
            if grp == gid:
                _say_parts([("brand", f"    {name:<16}"), ("dim", desc)])
    _say_parts([("dim", "\n  keys:  "), ("brand", "/"), ("dim", " menu   "),
                ("brand", "TAB"), ("dim", " autofill   "),
                ("brand", "up/down"), ("dim", " browse menu   "),
                ("brand", "ctrl-c"), ("dim", " clear line")])
    _say_parts([("dim", "  found a bug / want a feature?  "),
                ("link", "https://github.com/Kenzy-Zero/kenze/issues"), ("dim", "\n")])


def h_clear(st, arg):
    os.system("cls" if os.name == "nt" else "clear")


HANDLERS = {
    "load": h_load, "peek": h_peek, "show": h_peek, "schema": h_schema,
    "count": h_count, "stats": h_stats, "plot": h_plot, "history": h_history,
    "steps": h_steps, "pipeline": h_steps,
    "undo": h_undo, "reset": h_reset, "sql": h_sql, "eject": h_eject,
    "save": h_save, "run": h_run, "convert": h_convert, "pwd": h_pwd, "cd": h_cd,
    "check": h_check, "validate": h_validate, "join": h_join, "diff": h_diff,
    "pivot": h_pivot, "unpivot": h_unpivot, "split": h_split,
    "partition": h_partition, "traintest": h_traintest, "dryrun": h_dryrun, "set": h_set,
    "open": h_open, "recipe": h_recipe,
    "help": h_help, "clear": h_clear,
}
for _a in ("assert", "assert-unique", "assert-not-null"):
    HANDLERS[_a] = (lambda c: (lambda st, arg: _add_assert(st, c, arg)))(_a)
for _c in ("keep", "drop", "filter", "rename", "cast", "fillna", "mask",
           "scale", "bin", "encode", "onehot", "clip-outliers", "dedup", "clip",
           "sample", "head"):
    HANDLERS[_c] = (lambda c: (lambda st, arg: _add_step(st, c, arg)))(_c)


def dispatch(st, line):
    """Return False to keep looping, True to exit."""
    line = line.strip()
    if not line:
        return False
    if line.startswith("/"):
        line = line[1:].strip()
    if not line:
        return False
    parts = line.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    if cmd in ("exit", "quit", "q"):
        return True
    fn = HANDLERS.get(cmd)
    if not fn:
        _say(f"  unknown command: {cmd}   (type `help` or `/`)", "warn")
        return False
    try:
        fn(st, arg)
    except Exception as e:
        _say(f"  Error: {e}", "err")   # friendly, never a traceback
    return False


# ------------------------------------------------------------ the banner

def _plain_banner(have_ptk):
    print("\n  kenze - interactive data session")
    print("  type  /  for commands, `help` for the list.  `load <file>` to begin,"
          " `exit` to leave.")
    if not have_ptk:
        print("  (install `pip install kenze[shell]` for colours + the / menu"
              " + autocomplete)")
    print()


def _rich_banner(animate=True):
    import time

    def emit(chunks, delay=0.0):
        _PF(_FT(chunks), style=_STYLE)
        if animate and delay:
            time.sleep(delay)

    print()
    for line, col in zip(_WORDMARK, _WORD_COLORS):
        emit([(f"fg:{col} bold", line)], 0.03)
    emit([("", "")])
    emit([("fg:#ffd479 bold", "   big-file data prep that never runs out of memory"),
          ("class:dim", "   -   powered by DuckDB")], 0.02)
    emit([("class:rule", "   " + "-" * 60)], 0.02)
    emit([("class:accent2", "   This is the "), ("class:brand", "kenze shell"),
          ("class:accent2", "  -  where the wrangling happens.")], 0.02)
    emit([("class:dim", "   load a file, stack simple steps (each previews live),"
                        " then save a recipe or run it.")], 0.02)
    emit([("", "")])
    emit([("class:dim", "   version   "), ("class:accent", __version__),
          ("class:dim", "   -  interactive shell (preview)")], 0.02)
    emit([("class:dim", "   PyPI      "),
          ("class:link", "https://pypi.org/project/kenze/")], 0.02)
    emit([("class:dim", "   GitHub    "),
          ("class:link", "https://github.com/Kenzy-Zero/kenze")], 0.02)
    emit([("class:dim", "   Docs      "),
          ("class:link", "https://github.com/Kenzy-Zero/kenze/blob/main/SHELL.md")], 0.02)
    emit([("class:dim", "   Issues    "),
          ("class:link", "https://github.com/Kenzy-Zero/kenze/issues")], 0.02)
    emit([("", "")])
    emit([("class:dim", "   type  "), ("class:brand", "/"),
          ("class:dim", "  for the command menu     "),
          ("class:brand", "help"), ("class:dim", "  for a guided list     "),
          ("class:brand", "exit"), ("class:dim", "  to leave")], 0.02)
    emit([("", "")])


# --------------------------------------------------------- the two REPLs

def _basic_repl(st):
    """No prompt_toolkit: a plain input() loop (no colour / menu / autocomplete)."""
    while True:
        try:
            line = input("kenze> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if dispatch(st, line):
            break
    st.con.close()
    return 0


def make_completer(st):
    """The / command palette + schema-aware column + file-path autocomplete.

    Built lazily (prompt_toolkit is an optional extra); returned so it can be
    unit-tested against real session state.
    """
    from prompt_toolkit.completion import Completer, Completion, PathCompleter
    from prompt_toolkit.document import Document

    paths = PathCompleter(expanduser=True)

    class KenzeCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            stripped = text.lstrip()
            # completing the command itself (first token)?
            if " " not in stripped:
                slash = stripped.startswith("/")
                base = stripped[1:] if slash else stripped
                for name, (_grp, desc) in COMMANDS.items():
                    if name.startswith(base.lower()):
                        shown = ("/" + name) if slash else name
                        yield Completion(shown, start_position=-len(stripped),
                                         display=name, display_meta=desc)
                return
            cmd = stripped.split(None, 1)[0].lstrip("/").lower()
            if cmd in FILE_CMDS:
                after = stripped.split(None, 1)
                remainder = after[1] if len(after) > 1 else ""
                opts = CMD_GUIDE.get(cmd, (None, None, None, []))[3]
                # for run/convert: once a plain output file is typed, complete OPTIONS
                if opts and remainder.lstrip()[:1] not in ("'", '"'):
                    toks = remainder.split()
                    new_tok = text.endswith((" ", "\t"))
                    if len(toks) >= 2 or (len(toks) == 1 and new_tok):
                        frag = "" if new_tok else toks[-1]
                        for o in opts:
                            if o.lower().startswith(frag.lower()):
                                yield Completion(o, start_position=-len(frag),
                                                 display_meta="option")
                        return
                # otherwise complete the path (the WHOLE remainder - may have spaces)
                cur_path = remainder
                if cur_path[:1] in ("'", '"'):        # a quoted path being typed
                    cur_path = cur_path[1:]
                sub = Document(cur_path, len(cur_path))
                for c in paths.get_completions(sub, complete_event):
                    yield c
                return
            cur = text.split()[-1] if not text.endswith((" ", "\t")) else ""
            if cmd in _COL_METHODS and ":" in cur:    # method/type after a colon
                frag = cur.rsplit(":", 1)[-1]
                for m in _COL_METHODS[cmd]:
                    if m.lower().startswith(frag.lower()):
                        yield Completion(m, start_position=-len(frag), display_meta="type")
                return
            if cmd == "set":                          # setting names
                for s in CMD_GUIDE["set"][3]:
                    if s.startswith(cur.lower()):
                        yield Completion(s, start_position=-len(cur), display_meta="setting")
                return
            if cmd in COLUMN_CMDS and st.cols and ":" not in cur:
                if cmd == "filter":
                    # only suggest a column for the FIRST bare word of the
                    # condition; once an operator/space/quote appears it's SQL
                    rest = stripped.split(None, 1)
                    rest = rest[1] if len(rest) > 1 else ""
                    if any(c in rest for c in " =<>!()'\""):
                        return
                frag = cur.rsplit(",", 1)[-1]   # complete the col after a comma too
                low = frag.lower()
                for col in st.cols:
                    if col.lower().startswith(low):
                        yield Completion(col, start_position=-len(frag),
                                         display_meta="column")

    return KenzeCompleter()


def _make_keys():
    """TAB = autofill the top suggestion (not navigate); shift-TAB steps back."""
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("tab")
    def _(event):
        b = event.current_buffer
        cs = b.complete_state
        if cs and cs.completions:
            b.apply_completion(cs.current_completion or cs.completions[0])
        else:
            b.start_completion(select_first=True)

    @kb.add("s-tab")
    def _(event):  # noqa: F811
        b = event.current_buffer
        if b.complete_state:
            b.complete_previous()
        else:
            b.start_completion(select_last=True)

    return kb


def _pretty_repl(st):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.shortcuts import CompleteStyle

    def toolbar():
        # live "what to type next" guidance, driven by the current input line
        try:
            from prompt_toolkit.application import get_app
            typed = get_app().current_buffer.text
        except Exception:
            typed = ""
        hint = _guide_hint(typed, bool(st.input))
        left = []
        if hint:
            kind, msg = hint
            marker = "OK" if kind == "ready" else "->"
            left = [("class:tb-key", f"  {marker} "),
                    ("class:bottom-toolbar", f"{msg}    ")]
        elif st.input:
            left = [("class:bottom-toolbar", f"  {os.path.basename(st.input)}  "),
                    ("class:tb-dim", f"{len(st.steps)} steps    ")]
        else:
            left = [("class:tb-dim", "  no file loaded    ")]
        right = [
            ("class:tb-key", "TAB"), ("class:bottom-toolbar", " next   "),
            ("class:tb-key", "/"), ("class:bottom-toolbar", " menu   "),
            ("class:tb-key", "exit"), ("class:bottom-toolbar", " quit "),
        ]
        return FormattedText(left + right)

    prompt_msg = FormattedText([("class:brand", "kenze"), ("class:arrow", " > ")])
    session = PromptSession(
        message=prompt_msg,
        completer=make_completer(st),
        complete_style=CompleteStyle.COLUMN,
        complete_while_typing=True,
        key_bindings=_make_keys(),
        history=InMemoryHistory(),
        bottom_toolbar=toolbar,
        style=_STYLE,
    )
    while True:
        try:
            line = session.prompt()
        except KeyboardInterrupt:
            continue          # Ctrl-C clears the line, stays in the shell
        except EOFError:
            break             # Ctrl-D leaves
        if dispatch(st, line):
            break
    _say("  bye", "dim")
    st.con.close()
    return 0


def run_shell(argv=None):
    global _RICH, _STYLE, _PF, _FT
    import sys

    try:
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.styles import Style
        have_ptk = True
    except Exception:
        have_ptk = False

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    st = ShellState()
    if have_ptk and interactive:
        try:
            _RICH = True
            _STYLE = Style.from_dict(_STYLE_DICT)
            _PF, _FT = print_formatted_text, FormattedText
            _rich_banner(animate=True)
            return _pretty_repl(st)
        except Exception as e:
            # some terminals (git-bash/mintty/cygwin) aren't a real Windows
            # console -> prompt_toolkit can't drive them; drop to the plain loop
            if type(e).__name__ != "NoConsoleScreenBufferError":
                raise
            _RICH = False

    # fallback: no prompt_toolkit, piped input, or an undriveable console
    _plain_banner(have_ptk)
    return _basic_repl(st)
