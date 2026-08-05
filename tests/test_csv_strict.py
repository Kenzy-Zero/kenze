"""A CSV that breaks the standard must be readable when you ask for it - and
must not be quietly repaired when you didn't.

Found by dogfooding on real data: a Spark-written `part-*-c000.csv` couldn't be
opened by kenze at all, and BOTH documented escape hatches (--skip-bad-lines,
--errors) failed byte-identically to the plain call - because ignore_errors only
skips rows the parser can still parse, and a non-RFC-4180 file dies in the
parser's state machine before any row exists to skip.

The cure is DuckDB's strict_mode=false, but it does not belong on those flags:
it ACCEPTS a non-conforming row and discards the overflow, where ignore_errors
DROPS it and --errors hands it to you. So it gets its own switch,
--no-strict-csv, and the tests below pin both halves of that boundary.

The fixture reproduces the failure with mixed line endings (\\n throughout,
\\r\\n on one row), which is what real Spark output does when its inputs
disagree. The break has to sit past the sniffer's 20480-row sample: inside it,
DuckDB just picks a dialect that copes and there is no bug to see.
"""
from __future__ import annotations

import subprocess
import sys

import duckdb
import pytest

import kenze
from conftest import fs

CLEAN_ROWS = 30000            # comfortably past DuckDB's 20480-row sniff sample
TOTAL_ROWS = CLEAN_ROWS + 1


def kenze_cli(*args):
    return subprocess.run([sys.executable, "-m", "kenze", *args],
                          capture_output=True, text=True)


@pytest.fixture
def not_rfc4180(tmp_path):
    """A CSV that DuckDB's strict parser refuses: one \\r\\n among \\n."""
    p = tmp_path / "part-00000-abc-c000.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        f.write("id,name\n")
        for i in range(CLEAN_ROWS):
            f.write(f"{i},value {i}\n")
        f.write(f"{CLEAN_ROWS},tail\r\n")      # the standard-breaking row
    return fs(p)


@pytest.fixture
def ragged(tmp_path):
    """A well-formed CSV with one row carrying an extra field.

    Same size trick as above, for a second reason: on a handful of lines the
    sniffer gives up on the comma entirely and reports one column called
    "id,name", so a small fixture would measure DuckDB's dialect guess instead
    of what happens to the ragged row.
    """
    p = tmp_path / "ragged.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        f.write("id,name\n")
        for i in range(CLEAN_ROWS):
            f.write(f"{i},v{i}\n")
        f.write(f"{CLEAN_ROWS},tail,EXTRA\n")   # one field too many
    return fs(p)


# --------------------------------------------------------------- the bug

def test_fixture_really_is_unreadable_strictly(not_rfc4180):
    """Guard the guard: if DuckDB ever starts accepting this file, everything
    below would pass for the wrong reason and we'd want to know."""
    con = duckdb.connect()
    try:
        with pytest.raises(duckdb.Error):
            con.execute(f"SELECT count(*) FROM '{not_rfc4180}'").fetchone()
        # and ignore_errors alone is NOT the cure - this is the whole point
        with pytest.raises(duckdb.Error):
            con.execute(f"SELECT count(*) FROM read_csv('{not_rfc4180}', "
                        f"auto_detect=true, ignore_errors=true)").fetchone()
    finally:
        con.close()


def test_no_strict_csv_opens_it(not_rfc4180):
    r = kenze_cli("--no-strict-csv", "profile", not_rfc4180)
    assert r.returncode == 0, r.stderr[-300:]
    assert f"{TOTAL_ROWS:,} rows" in r.stdout


@pytest.mark.parametrize("cmd", ["profile", "peek", "stats"])
def test_inspect_commands_accept_the_flag(not_rfc4180, cmd):
    """The read-only commands are the ones you reach for FIRST on a file you
    can't open, so the flag has to reach them - the global flags used to be
    dropped before they ever got to profile/peek/stats."""
    r = kenze_cli("--no-strict-csv", cmd, not_rfc4180)
    assert r.returncode == 0, f"{cmd}: {r.stderr[-300:]}"


def test_transform_writes_every_row(not_rfc4180, tmp_path, sql):
    out = fs(tmp_path / "clean.csv")
    r = kenze_cli("--no-strict-csv", "keep", not_rfc4180, "--cols", "id", "-o", out, "-q")
    assert r.returncode == 0, r.stderr[-300:]
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == TOTAL_ROWS


def test_python_api_takes_strict(not_rfc4180):
    assert kenze.profile(not_rfc4180, strict=False) == TOTAL_ROWS


# ------------------------------------------------- finding out what to type

def test_check_diagnoses_instead_of_crashing(not_rfc4180):
    """`check` exists to tell you whether a file is readable. Dying on the file
    it was pointed at is the one thing it must never do."""
    r = kenze_cli("check", not_rfc4180)
    assert r.returncode == 0, r.stderr[-300:]
    assert "readable rows" in r.stdout
    assert "RFC 4180" in r.stdout                  # names what's actually wrong
    assert "--no-strict-csv" in r.stdout           # and how to get past it


def test_error_names_the_flag_that_fixes_it(not_rfc4180):
    """DuckDB names its own parameter (strict_mode=false), which a kenze user
    has no way to type. The plain call still fails - it should - but it has to
    fail pointing at something runnable."""
    r = kenze_cli("profile", not_rfc4180)
    assert r.returncode != 0
    msg = r.stderr + r.stdout
    assert "Traceback" not in msg
    assert "--no-strict-csv" in msg


# ------------------------------------------- the boundary: rows vs the file

def test_relaxing_is_opt_in_not_automatic(not_rfc4180):
    """kenze relaxes the standard because you asked, never on its own: a file
    silently repaired is a file you stop trusting."""
    assert kenze_cli("profile", not_rfc4180).returncode != 0


def test_skip_bad_lines_does_not_silently_relax_the_standard(ragged, tmp_path, sql):
    """THE regression this whole module exists to prevent.

    strict_mode=false would let `N,tail,EXTRA` through as `N,tail` - the
    overflow discarded, no error, no reject. If --skip-bad-lines ever picks
    that up for free, a broken file starts reporting itself as clean.
    """
    out = fs(tmp_path / "ragged_out.csv")
    r = kenze_cli("--skip-bad-lines", "keep", ragged, "--cols", "id", "-o", out, "-q")
    assert r.returncode == 0, r.stderr[-300:]
    # dropped, not truncated: the count is short by exactly the ragged row
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == CLEAN_ROWS


def test_errors_still_quarantines_bad_rows(ragged, tmp_path, sql):
    """--errors keeps its quarantine file: the bad row must be handed back, not
    absorbed."""
    out = fs(tmp_path / "q_out.csv")
    bad = tmp_path / "q_bad.csv"
    r = kenze_cli("--errors", fs(bad), "keep", ragged, "--cols", "id", "-o", out, "-q")
    assert r.returncode == 0, r.stderr[-300:]
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == CLEAN_ROWS
    assert bad.exists() and bad.stat().st_size > 0


def test_no_strict_csv_keeps_the_ragged_row(ragged, tmp_path, sql):
    """The other side of the same boundary, stated so the trade-off is visible:
    --no-strict-csv keeps that row (minus the overflow). That is what the flag
    is for, and why it is not the default."""
    out = fs(tmp_path / "loose.csv")
    r = kenze_cli("--no-strict-csv", "keep", ragged, "--cols", "id", "-o", out, "-q")
    assert r.returncode == 0, r.stderr[-300:]
    assert sql(f"SELECT count(*) FROM '{out}'")[0][0] == TOTAL_ROWS


def test_shell_has_the_same_switch(not_rfc4180):
    """The shell is a first-class front end, not a demo: whatever unsticks a
    file on the CLI has to unstick it there too."""
    from kenze import shell
    st = shell.ShellState()
    assert st.strict_csv is True                      # strict by default, same as the CLI
    shell.dispatch(st, "set strict-csv off")
    assert st.strict_csv is False
    assert st.build_spec().get("strict_csv") is False  # and it reaches the query
    shell.dispatch(st, "load " + not_rfc4180)
    assert st.input == not_rfc4180
    assert st.cols == ["id", "name"]


def test_shell_error_points_at_the_shell_fix(not_rfc4180, capsys):
    """...and it must name `set strict-csv off`, not the CLI flag - telling
    somebody inside the shell to retype their command with --no-strict-csv is
    advice they can't take."""
    from kenze import shell
    st = shell.ShellState()
    shell.dispatch(st, "load " + not_rfc4180)   # schema only - this much succeeds
    shell.dispatch(st, "count id")              # the full scan is where it breaks
    out = capsys.readouterr().out
    assert "set strict-csv off" in out
    assert "--no-strict-csv" not in out


def test_a_glob_alone_does_not_relax_the_standard(tmp_path):
    """Reading many files isn't a request for leniency - the strict_mode escape
    must not leak in through union_by_name."""
    from kenze.ops import _source
    src = _source(fs(tmp_path / "sales_*.csv"))
    assert "union_by_name" in src and "strict_mode" not in src


def test_clean_file_is_untouched_by_the_flags(people):
    """Neither flag may drop or alter a row in a well-formed file."""
    for flag in ("--skip-bad-lines", "--no-strict-csv"):
        r = kenze_cli(flag, "profile", people)
        assert r.returncode == 0 and "12 rows" in r.stdout, flag
