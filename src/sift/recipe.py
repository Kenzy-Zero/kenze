"""Tiny recipe parser - a readable .dq file, no YAML dependency.

    input:  data/sales.parquet
    keep:   [id, city, amount]
    filter: amount > 0
    dedup:  id
    sample: 50000
    output: out/clean.csv

Only rule: one `key: value` per line, `[a, b, c]` for lists, `#` comments.
"""
from __future__ import annotations

import difflib

_REQUIRED = ("input", "output")

KNOWN_KEYS = {
    "input", "output", "keep", "drop", "filter",
    "dedup", "sample", "head", "bbox",
}

REFERENCE = """sift recipe (.dq) format
========================
A recipe is a plain text file. One `key: value` per line; `#` starts a comment.
Run it with:   dq run myrecipe.dq

Steps (use only the ones you need, in any order):

  input:   PATH                          (required) file to read: csv / parquet / json
  keep:    [col, col, col]               keep only these columns
  drop:    [col, col]                    remove these columns
  filter:  amount > 0                    keep only rows matching this condition
  bbox:    minlon,minlat,maxlon,maxlat   keep only rows inside a lat/lon box
  dedup:   id                            drop duplicate rows (a column name, or: all)
  sample:  50000                         keep N random rows
  head:    100                           keep the first N rows
  output:  PATH                          (required) where to write the result

Tip: every step is the same word as a `dq` command. Know the commands, know recipes.

Example:

  input:  data/sales.parquet
  keep:   [id, city, amount]
  filter: amount > 0
  dedup:  id
  output: out/clean.csv
"""


def _strip_comment(line: str) -> str:
    """Drop a trailing #comment, but not a # that sits inside quotes."""
    inq = None
    for i, ch in enumerate(line):
        if inq:
            if ch == inq:
                inq = None
        elif ch in "\"'":
            inq = ch
        elif ch == "#":
            return line[:i]
    return line


def parse(text: str) -> dict:
    spec: dict = {}
    for raw in text.splitlines():
        s = _strip_comment(raw).strip()
        if not s or ":" not in s:
            continue
        key, val = s.split(":", 1)          # split on FIRST colon (keeps C:\ paths intact)
        key, val = key.strip().lower(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = [x.strip() for x in val[1:-1].split(",") if x.strip()]
        elif (val[:1], val[-1:]) in (('"', '"'), ("'", "'")):
            val = val[1:-1]
        spec[key] = val
    for k in spec:
        if k not in KNOWN_KEYS:
            hint = difflib.get_close_matches(k, KNOWN_KEYS, n=1)
            suffix = f" (did you mean '{hint[0]}'?)" if hint else ""
            raise ValueError(
                f"unknown recipe step '{k}'{suffix}. "
                f"valid steps: {', '.join(sorted(KNOWN_KEYS))}"
            )
    missing = [k for k in _REQUIRED if k not in spec]
    if missing:
        raise ValueError(f"recipe is missing: {', '.join(missing)}")
    return spec
