"""End-to-end CLI: prove the installed `kenze` entry point actually runs. Uses
the same interpreter running the tests (editable install locally, pip install
in CI), so `python -m kenze ...` exercises the real console command."""
from __future__ import annotations

import json
import subprocess
import sys

from conftest import fs


def kenze_cli(*args, **kw):
    return subprocess.run([sys.executable, "-m", "kenze", *args],
                          capture_output=True, text=True, **kw)


def test_version():
    r = kenze_cli("--version")
    assert r.returncode == 0 and "kenze" in r.stdout


def test_profile(people):
    r = kenze_cli("profile", people)
    assert r.returncode == 0 and "12 rows" in r.stdout


def test_filter_writes_output(people, tmp_path, sql):
    out = fs(tmp_path / "cli.csv")
    r = kenze_cli("filter", people, "--where", "amount > 100", "-o", out, "-q")
    assert r.returncode == 0
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == 9  # 9 of 12 rows match


def test_filter_n_limits_the_result(people, tmp_path, sql):
    """--n caps the output so you can eyeball a filter before writing it all."""
    out = fs(tmp_path / "peek.csv")
    r = kenze_cli("filter", people, "--where", "amount > 100", "--n", "3", "-o", out, "-q")
    assert r.returncode == 0
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == 3
    # the filter still applies - a limit must never leak non-matching rows
    assert sql(f"SELECT count(*) FROM '{out}' WHERE amount <= 100")[0][0] == 0


def test_dedup_n_limits_the_result(people, tmp_path, sql):
    out = fs(tmp_path / "dpeek.csv")
    r = kenze_cli("dedup", people, "--n", "4", "-o", out, "-q")
    assert r.returncode == 0
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == 4


def test_n_is_never_an_ambiguous_abbreviation(people, tmp_path):
    """`--n` must not be read as an abbreviation of --no-disk-check/--no-history.

    argparse abbreviates unknown long options, so without allow_abbrev=False the
    parse dies with "ambiguous option: --n" before the subcommand sees it. Python
    3.13 tolerates it, 3.9 and 3.11 do not - so only CI caught this. Every command
    that takes --n is checked here.
    """
    cases = [
        ("peek", ["peek", people, "--n", "5"]),
        ("sample", ["sample", people, "--n", "5", "-o", fs(tmp_path / "s.csv"), "-q"]),
        ("head", ["head", people, "--n", "5", "-o", fs(tmp_path / "h.csv"), "-q"]),
        ("filter", ["filter", people, "--where", "amount > 100", "--n", "2",
                    "-o", fs(tmp_path / "f.csv"), "-q"]),
        ("dedup", ["dedup", people, "--n", "5", "-o", fs(tmp_path / "d.csv"), "-q"]),
    ]
    for name, argv in cases:
        r = kenze_cli(*argv)
        assert "ambiguous" not in r.stderr, f"{name}: {r.stderr.strip()[-120:]}"
        assert r.returncode == 0, f"{name} exited {r.returncode}: {r.stderr.strip()[-160:]}"


def test_validate_exit_code(people, tmp_path):
    """validate returns exit 1 when the schema doesn't match (cron-safe)."""
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"columns": {"id": "VARCHAR"},
                                  "not_null": ["missing_col"]}), encoding="utf-8")
    r = kenze_cli("validate", people, "--schema", str(schema))
    assert r.returncode == 1  # problems found -> non-zero for pipelines


def test_recipe_reference_prints():
    r = kenze_cli("recipe")
    assert r.returncode == 0 and "input:" in r.stdout and "output:" in r.stdout


def test_bad_command_is_friendly_not_traceback(tmp_path):
    r = kenze_cli("profile", str(tmp_path / "nope.csv"))
    assert r.returncode != 0
    assert "Traceback" not in r.stderr        # clean error, no stack dump
    assert "Error" in (r.stderr + r.stdout) or "no such file" in (r.stderr + r.stdout)
