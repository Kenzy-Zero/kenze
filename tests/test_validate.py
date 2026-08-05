"""validate: a file against a written-down contract, and the scaffold that
makes writing one possible.

Found by Ken in the shell: `validate kenze_demo.csv` - the natural thing to
type - died with `Expecting value: line 1 column 1 (char 0)`, json's complaint
about being handed a CSV. Two failures in one: the argument is the SCHEMA, not
the data, and nothing said so. And underneath that, a third: you cannot use
validate at all until a schema exists, and hand-writing JSON is exactly the
friction kenze is supposed to remove.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import kenze
from conftest import fs
from kenze import shell


def kenze_cli(*args):
    return subprocess.run([sys.executable, "-m", "kenze", *args],
                          capture_output=True, text=True)


# --------------------------------------------------------------- scaffolding

def test_scaffold_writes_the_contract_the_file_already_satisfies(people, tmp_path):
    out = fs(tmp_path / "schema.json")
    kenze.scaffold_schema(people, out)
    schema = json.loads(open(out, encoding="utf-8").read())

    assert list(schema["columns"]) == ["id", "name", "city", "amount"]
    assert schema["columns"]["id"] == "BIGINT"
    assert schema["columns"]["name"] == "VARCHAR"
    # city has an empty value in the fixture, so it is NOT claimed as not-null:
    # the scaffold reports what is true today, it does not aspire
    assert "city" not in schema["not_null"]
    assert "id" in schema["not_null"]


def test_a_scaffolded_schema_validates_its_own_file(people, tmp_path):
    """The obvious round trip, and the one that would break silently if the
    scaffold wrote types in a form validate could not read back."""
    out = fs(tmp_path / "schema.json")
    kenze.scaffold_schema(people, out)
    assert kenze.validate(people, out) == 0


def test_scaffold_from_the_cli(people, tmp_path):
    out = fs(tmp_path / "s.json")
    r = kenze_cli("validate", people, "--scaffold", out)
    assert r.returncode == 0, r.stderr[-300:]
    assert "wrote" in r.stdout
    assert json.loads(open(out, encoding="utf-8").read())["columns"]


# ------------------------------------------------------------- what it catches

def test_it_catches_a_renamed_column_and_new_nulls(people, tmp_path, sql):
    schema = fs(tmp_path / "schema.json")
    kenze.scaffold_schema(people, schema)

    later = tmp_path / "next_month.csv"
    later.write_text("id,name,town,amount\n1,Alice,London,100\n,Bob,Paris,200\n",
                     encoding="utf-8")
    problems = kenze.validate(fs(later), schema)
    assert problems >= 2                       # the rename and the null


def test_the_exit_code_is_the_point(people, tmp_path):
    """It is a gate: cron and CI act on the exit code, not on the words."""
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"columns": {"nope": "VARCHAR"}}), encoding="utf-8")
    assert kenze_cli("validate", people, "--schema", fs(schema)).returncode == 1

    good = fs(tmp_path / "good.json")
    kenze.scaffold_schema(people, good)
    assert kenze_cli("validate", people, "--schema", good).returncode == 0


# ------------------------------------------------- saying what actually went wrong

def test_handing_it_a_data_file_explains_itself(people, tmp_path):
    """THE regression guard. json's own message for this is
    "Expecting value: line 1 column 1 (char 0)", which tells you nothing."""
    r = kenze_cli("validate", people, "--schema", people)
    msg = r.stderr + r.stdout
    assert r.returncode != 0
    assert "Traceback" not in msg
    assert "not valid json" in msg
    assert "looks like a DATA file" in msg
    assert "--scaffold" in msg                 # and how to get out of it


def test_a_missing_schema_file_says_how_to_make_one(people, tmp_path):
    r = kenze_cli("validate", people, "--schema", fs(tmp_path / "nope.json"))
    msg = r.stderr + r.stdout
    assert "no such schema file" in msg and "--scaffold" in msg


def test_no_schema_at_all_is_not_an_argparse_error(people):
    """--schema used to be required=True, so omitting it produced argparse's
    usage dump. It now explains the concept and offers the way forward."""
    r = kenze_cli("validate", people)
    msg = r.stderr + r.stdout
    assert r.returncode != 0
    assert "--scaffold" in msg


# ------------------------------------------------------------------- the shell

@pytest.fixture
def st(people):
    s = shell.ShellState()
    shell.dispatch(s, f"load {people}")
    return s


def test_shell_catches_the_data_file_mistake(st, people, capsys):
    """Exactly what Ken typed."""
    shell.dispatch(st, f"validate {people}")
    out = capsys.readouterr().out
    assert "not the data file" in out
    assert "--scaffold" in out
    assert "Expecting value" not in out


def test_shell_scaffolds_then_validates(st, tmp_path, capsys):
    out = fs(tmp_path / "s.json")
    shell.dispatch(st, f"validate --scaffold {out}")
    assert "wrote" in capsys.readouterr().out

    shell.dispatch(st, f"validate {out}")
    assert "OK - schema matches" in capsys.readouterr().out


def test_shell_accepts_the_cli_spelling(st, tmp_path, capsys):
    """Somebody who read the docs types `--schema`; refusing that helps nobody."""
    out = fs(tmp_path / "s.json")
    shell.dispatch(st, f"validate --scaffold {out}")
    capsys.readouterr()
    shell.dispatch(st, f"validate --schema {out}")
    assert "OK - schema matches" in capsys.readouterr().out


def test_shell_json_schema_is_not_mistaken_for_data(st, tmp_path, capsys):
    """.json is the schema's own format, so it must never trip the data-file
    guard - a bug in the first cut of that check."""
    out = fs(tmp_path / "s.json")
    shell.dispatch(st, f"validate --scaffold {out}")
    capsys.readouterr()
    shell.dispatch(st, f"validate {out}")
    assert "not the data file" not in capsys.readouterr().out


def test_shell_with_no_args_points_at_the_scaffold(st, capsys):
    shell.dispatch(st, "validate")
    out = capsys.readouterr().out
    assert "usage:" in out and "--scaffold" in out
