"""Tiny recipe parser - a readable .dq file, no YAML dependency.

    input:  data/sales.parquet
    keep:   [id, city, amount]
    filter: amount > 0
    types:  zip:VARCHAR
    fillna: city:Unknown
    rename: amount:total
    dedup:  id
    sample: 50000
    output: out/clean.csv

Only rule: one `key: value` per line, `[a, b, c]` for lists, `#` comments.
Values may reference variables: ${VAR} or {{ VAR }} (from --set or the
environment) so the same recipe runs every day with a changing date/path.
"""
from __future__ import annotations

import difflib
import os
import re

_REQUIRED = ("input", "output")

KNOWN_KEYS = {
    "input", "output", "keep", "drop", "filter", "bbox",
    "types", "fillna", "mask", "mask_method", "rename",
    "dedup", "sample", "head",
}

REFERENCE = """kenze recipe (.dq) format
=========================
A recipe is a plain text file. One `key: value` per line; `#` starts a comment.
Run it with:   kenze run myrecipe.dq

Steps (use only the ones you need, in any order):

  input:    PATH                          (required) file to read: csv / parquet / json / .gz / s3://...
  keep:     [col, col, col]               keep only these columns
  drop:     [col, col]                    remove these columns
  filter:   amount > 0                    keep only rows matching this condition
  bbox:     minlon,minlat,maxlon,maxlat   keep only rows inside a lat/lon box
  types:    zip:VARCHAR, id:VARCHAR       cast columns to a type (stops leading-zero loss)
  fillna:   city:Unknown, score:0         replace nulls in a column with a value
  mask:     email, ssn                    mask sensitive columns (see mask_method)
  mask_method: hash                       hash (default) | redact | null
  rename:   old:new, amount:total         rename columns
  dedup:    id                            drop duplicate rows (a column name, or: all)
  sample:   50000                         keep N random rows
  head:     100                           keep the first N rows
  output:   PATH                          (required) where to write the result

Variables:  input: data/sales_${DAY}.parquet    (fill with --set DAY=2026-07-14 or the environment)

Tip: every step is the same word as a `kenze` command. Know the commands, know recipes.

Example:

  input:  data/sales.parquet
  keep:   [id, city, amount]
  types:  zip:VARCHAR
  filter: amount > 0
  dedup:  id
  output: out/clean.csv
"""

_VAR = re.compile(r"\$\{(\w+)\}|\{\{\s*(\w+)\s*\}\}")


def render(text: str, variables: dict | None = None) -> str:
    """Substitute ${VAR} / {{ VAR }} from `variables`, falling back to os.environ."""
    env = dict(os.environ)
    if variables:
        env.update(variables)

    def sub(m):
        name = m.group(1) or m.group(2)
        if name not in env:
            raise ValueError(f"recipe variable '{name}' is not set (use --set {name}=... or an env var)")
        return env[name]

    return _VAR.sub(sub, text)


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


def parse(text: str, variables: dict | None = None) -> dict:
    text = render(text, variables)
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
