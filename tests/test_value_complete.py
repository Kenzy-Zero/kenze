"""Value autocomplete: TAB inside a quoted condition offers the column's real
values, with their real counts.

This is the feature that turns "no SQL required" from a claim about syntax into
a claim about knowledge - you no longer have to know what is IN the file either.
Which means the numbers beside each value have to be true, the list has to
follow the pipeline you have already built, and the whole thing has to stay off
the critical path of typing.
"""
from __future__ import annotations

import csv

import pytest

from conftest import fs
from kenze import shell

# 600 London / 300 Paris / 100 Tokyo / 20 with an apostrophe in the name
CITIES = ["London"] * 600 + ["Paris"] * 300 + ["Tokyo"] * 100 + ["O'Brien Town"] * 20
# order_ref is f"ref-{i:08d}" over 1020 rows, so this prefix matches exactly ten
REF_PREFIX = "ref-0000000"


@pytest.fixture
def cities(tmp_path):
    p = tmp_path / "cities.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "city", "order_ref"])
        for i, c in enumerate(CITIES):
            w.writerow([i, c, f"ref-{i:08d}"])
    return fs(p)


@pytest.fixture
def st(cities):
    s = shell.ShellState()
    shell.dispatch(s, f"load {cities}")
    return s


def completions(st, text, tab=True):
    """Drive the real completer the way prompt_toolkit does."""
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document
    c = shell.make_completer(st)
    return list(c.get_completions(Document(text, len(text)),
                                  CompleteEvent(completion_requested=tab)))


# ----------------------------------------------------- where it should trigger

@pytest.mark.parametrize("text,expected", [
    ("filter city = '",                  ("city", "")),
    ("filter city = 'Lon",               ("city", "Lon")),
    ("filter city='",                    ("city", "")),
    ("filter country != '",              None),          # unknown column
    ("filter city IN ('Lon",             ("city", "Lon")),
    ("filter city LIKE 'Lo",             ("city", "Lo")),
    ("filter city ILIKE 'lo",            ("city", "lo")),
    ('filter "home city" = \'Lon',       ("home city", "Lon")),
    ("filter CITY = 'lon",               ("city", "lon")),   # case-insensitive
    ("filter a = 'x' and city = 'L",     ("city", "L")),     # the LAST condition
    ("filter city = 'London'",           None),              # quote already closed
    ("filter amount > 100",              None),              # not a quoted value
    ("keep city",                        None),
])
def test_value_context(text, expected):
    assert shell.value_context(text, ["id", "city", "home city"]) == expected


def test_value_context_needs_columns():
    """Nothing is loaded yet -> nothing to offer, and no crash."""
    assert shell.value_context("filter city = '", []) is None


# ------------------------------------------------------------ what it measures

def test_offers_real_values_with_real_counts(st):
    rows, note = st.column_values("city")
    assert note is None
    assert rows == [("London", 600), ("Paris", 300), ("Tokyo", 100), ("O'Brien Town", 20)]


def test_high_cardinality_asks_for_a_letter_instead_of_listing(st):
    """A column with a value per row is not a list, it's a wall - but it is not
    useless either. With nothing typed, say what was measured and ask for a
    starting letter; with one, answer for real."""
    rows, note = st.column_values("order_ref")
    assert rows == []
    assert note and "type a letter to narrow them" in note

    rows, note = st.column_values("order_ref", REF_PREFIX)
    assert rows and all(str(v).startswith(REF_PREFIX) for v, _ in rows)
    assert "showing the top matches" in note


def test_narrowing_further_reuses_the_scan(st):
    """Once a column has been read in full, a longer prefix is answered from
    memory - otherwise every keystroke would be another pass over the column."""
    class SpyCon:                       # duckdb's execute is read-only, so wrap
        def __init__(self, real):
            self.real, self.queries = real, []

        def execute(self, q, *a, **k):
            self.queries.append(q)
            return self.real.execute(q, *a, **k)

        def __getattr__(self, name):
            return getattr(self.real, name)

    st.con = spy = SpyCon(st.con)
    st.column_values("city")                     # the one real scan
    before = len(spy.queries)
    st.column_values("city", "L")                # refined in memory
    st.column_values("city", "Lon")
    assert spy.queries[before:] == []            # no query of any kind, not just no scan
    assert [v for v, _ in st.column_values("city", "Lon")[0]] == ["London"]


def test_the_pipeline_sql_is_not_rebuilt_per_keystroke(st):
    """Building it runs a DESCRIBE, and ghost text asks for it on every key -
    on a large remote CSV that is a re-sniff of the file over the network."""
    class SpyCon:
        def __init__(self, real):
            self.real, self.queries = real, []

        def execute(self, q, *a, **k):
            self.queries.append(q)
            return self.real.execute(q, *a, **k)

        def __getattr__(self, name):
            return getattr(self.real, name)

    st.con = spy = SpyCon(st.con)
    st.current_query()
    before = len(spy.queries)
    for _ in range(5):
        st.current_query()
    assert len(spy.queries) == before
    # ...but a new step must invalidate it, or the values would go stale
    shell.dispatch(st, "filter city != 'Tokyo'")
    st.current_query()
    assert len(spy.queries) > before


def test_values_follow_the_pipeline_not_the_file(st):
    """THE correctness point. After a step, the values of a column are a
    different set - showing the file's original values would be a confident
    lie about data the user can see has changed."""
    assert ("Tokyo", 100) in st.column_values("city")[0]
    shell.dispatch(st, "filter city != 'Tokyo'")
    assert [v for v, _ in st.column_values("city")[0]] == ["London", "Paris", "O'Brien Town"]
    shell.dispatch(st, "undo")
    assert ("Tokyo", 100) in st.column_values("city")[0]


# -------------------------------------------------------------- the completions

def test_tab_offers_the_values(st):
    out = completions(st, "filter city = '")
    assert [c.display[0][1] for c in out] == ["London", "Paris", "Tokyo", "O'Brien Town"]
    assert out[0].display_meta[0][1] == "600 rows"


def test_typing_a_prefix_narrows_it(st):
    out = completions(st, "filter city = 'Lo")
    assert [c.display[0][1] for c in out] == ["London"]
    # replaces the fragment rather than appending to it
    assert out[0].start_position == -2


def test_silent_while_typing_only_speaks_on_tab(st):
    """complete_while_typing is on, and this completer asks DuckDB a question.
    Doing that per keystroke on a 60M-row file would lock the prompt - so it
    fires on an explicit TAB and never on the way past."""
    assert completions(st, "filter city = '", tab=False) == []


def test_the_reason_for_an_empty_list_reaches_the_user(st):
    """It must NOT be a Completion. kenze's TAB applies the top suggestion, so
    a note offered as a completion gets inserted as empty text and disappears -
    which is exactly what "I pressed TAB and nothing came up" looked like. It
    belongs in the toolbar, which can also read it without triggering a scan.
    """
    assert completions(st, "filter order_ref = '") == []
    st.column_values("order_ref")                     # as the TAB press just did
    kind, msg = shell._guide_hint("filter order_ref = '", True, st.cols, st)
    assert kind == "ready" and "type a letter to narrow them" in msg


def test_the_toolbar_never_triggers_a_scan(st):
    """It redraws on every keystroke, so it may only ever read the cache."""
    assert st._value_cache == {}
    shell._guide_hint("filter order_ref = '", True, st.cols, st)
    assert st._value_cache == {}


def test_no_match_offers_nothing_rather_than_everything(st):
    assert completions(st, "filter city = 'zzz") == []


# ---------------------------------------------------------------- and it works

def test_the_completed_value_is_valid_sql(st, cities):
    """End-to-end: take what TAB would insert, finish the condition the way the
    shell's auto-closed quote leaves it, and run it. A value containing an
    apostrophe is the case that would break a naive implementation."""
    out = completions(st, "filter city = 'O")
    assert len(out) == 1
    inserted = out[0].text
    assert inserted == "O''Brien Town"          # doubled for SQL, not backslashed

    shell.dispatch(st, f"filter city = '{inserted}'")
    n = st.con.execute(f"SELECT count(*) FROM ({st.current_query()}) _t").fetchone()[0]
    assert n == 20


def test_high_cardinality_values_still_complete_once_narrowed(st):
    """The wall becomes a list as soon as you give it a letter - which is how
    you would look for a device id anyway."""
    out = completions(st, f"filter order_ref = '{REF_PREFIX}")
    assert out and all(c.display[0][1].startswith(REF_PREFIX) for c in out)


def test_the_toolbar_tells_you_the_key_exists(st):
    """Discoverability is the shell's real gap, not features: a user who never
    presses TAB never learns this exists."""
    kind, msg = shell._guide_hint("filter city = '", True, st.cols)
    assert kind == "ready" and "TAB" in msg
    # ...and it doesn't hijack the hint anywhere else
    assert shell._guide_hint("filter amount > 0", True, st.cols)[1] == "press Enter to run"
    assert "TAB" not in shell._guide_hint("filter city = '", True, [])[1]


def test_pressing_tab_in_a_real_app_fills_the_value(st):
    """The completer returning the right thing is not the same as TAB working.

    This drives a real PromptSession over a pipe: type the condition, press an
    actual TAB, read the submitted line. Note the sleeps - TAB starts the
    completer as a BACKGROUND task, so sending TAB and Enter back to back
    submits the line before the completion has run and looks like a dead
    feature. That is the trap this test exists to document.
    """
    pytest.importorskip("prompt_toolkit")
    import asyncio

    from prompt_toolkit import PromptSession
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    async def type_then_tab(text):
        with create_pipe_input() as inp:
            sess = PromptSession(completer=shell.make_completer(st),
                                 key_bindings=shell._make_keys(),
                                 complete_while_typing=True,
                                 input=inp, output=DummyOutput())
            task = asyncio.create_task(sess.prompt_async("> "))
            inp.send_text(text)
            await asyncio.sleep(0.3)      # let the while-typing pass settle
            inp.send_text("\t")
            await asyncio.sleep(0.8)      # let the async completer finish
            inp.send_text("\r")
            return await task

    async def main():
        assert await type_then_tab("filter city = 'P") == "filter city = 'Paris'"
        assert await type_then_tab("filter city = '") == "filter city = 'London'"
        # the apostrophe value survives the round trip as valid SQL
        assert await type_then_tab("filter city = 'O") == "filter city = 'O''Brien Town'"

    asyncio.run(main())


# ------------------------------------------------- ghost text (auto-suggest)

def suggestion_for(st, text):
    """What the dim ghost text would say after typing `text`."""
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.document import Document
    s = shell.make_suggester(st).get_suggestion(None, Document(text, len(text)))
    return s.text if s else None


def test_ghost_text_finishes_the_value_as_you_type(st):
    st.column_values("city")                       # as a first TAB would
    assert suggestion_for(st, "filter city = 'L") == "ondon"
    assert suggestion_for(st, "filter city = 'Pa") == "ris"


def test_ghost_text_starts_at_the_very_first_keystroke(st):
    """It has to finish what you are typing from character one, not only once
    you reach a quoted value - a shell that stays blank until you are deep in a
    condition reads as one that does nothing."""
    assert suggestion_for(st, "f") == "ilter"
    assert suggestion_for(st, "lo") == "ad"
    assert suggestion_for(st, "/de") == "dup"       # through the slash prefix too


def test_ghost_text_finishes_column_names(st):
    assert suggestion_for(st, "filter ci") == "ty"
    assert suggestion_for(st, "keep ci") == "ty"
    assert suggestion_for(st, "keep id, ci") == "ty"   # after a comma


def test_ghost_text_finishes_settings_and_types(st):
    assert suggestion_for(st, "set str") == "ict-csv"
    assert suggestion_for(st, "cast id:VAR") == "CHAR"


def test_ghost_text_finishes_a_file_path(st, cities):
    import os
    folder, name = os.path.dirname(cities), os.path.basename(cities)
    assert suggestion_for(st, f"load {folder}/{name[:4]}") == name[4:]


def test_ghost_text_finishes_an_unquoted_value(st):
    """`filter city = Lon` is not valid SQL, but the shell repairs that shape on
    Enter, so it is a path users really travel - and it is the first thing
    somebody types before they learn about the quotes."""
    assert suggestion_for(st, "filter city = L") == "ondon"
    assert suggestion_for(st, "filter city L") == "ondon"      # no operator either
    assert suggestion_for(st, "filter city = zz") is None


def test_the_unquoted_suggestion_actually_runs(st):
    """Accepting it leaves `filter city = London`, which _repair_filter turns
    into valid SQL - so the whole path has to work end to end, not just look
    right in the prompt."""
    shell.dispatch(st, "filter city = " + "L" + suggestion_for(st, "filter city = L"))
    n = st.con.execute(f"SELECT count(*) FROM ({st.current_query()}) _t").fetchone()[0]
    assert n == 600


def test_ghost_text_never_finishes_a_number(st):
    """The sharpest edge in the whole feature.

    A half-typed word is obviously unfinished - `L` is not a city, so finishing
    it can only help. `id = 1` is already complete and valid, and quietly
    extending it to `10` changes what was asked for while looking like it
    merely completed it. TAB still lists numeric values, because there you can
    see what you are choosing.
    """
    assert suggestion_for(st, "filter id = 1") is None
    assert suggestion_for(st, "filter id > 10") is None
    assert completions(st, "filter id = '1")              # TAB still offers them


def test_ghost_text_offers_the_operator_you_do_not_know_to_type(st):
    """`filter city ` and then what? Nobody guesses `=` from a blank prompt."""
    assert suggestion_for(st, "filter city ") == "= "
    assert suggestion_for(st, "filter not_a_column ") is None
    assert suggestion_for(st, "keep city ") is None       # only filter takes a condition


def test_ghost_text_is_escaped_like_the_completion(st):
    st.column_values("city")
    assert suggestion_for(st, "filter city = 'O") == "''Brien Town"


def test_no_ghost_text_before_you_have_typed_anything(st):
    """With an empty fragment there is no word to finish. Silently proposing
    the most common value would be putting words in the user's mouth - TAB is
    the key for "show me the options"."""
    st.column_values("city")
    assert suggestion_for(st, "filter city = '") is None


def test_no_ghost_text_when_nothing_matches_or_it_does_not_apply(st):
    st.column_values("city")
    assert suggestion_for(st, "filter city = 'zzz") is None
    assert suggestion_for(st, "filter amount > 10") is None
    assert suggestion_for(st, "keep city") is None


def test_right_arrow_accepts_the_ghost_text_through_the_closing_quote(st):
    """0.9.5 + 0.10.0 regression guard, and the reason this needed a binding.

    prompt_toolkit only accepts a suggestion when the cursor is at the very end
    of the line - but kenze's auto-closing quote always leaves a `'` after it,
    so out of the box the ghost text appeared and the right-arrow just stepped
    over the quote. The two features cancelled each other out.
    """
    pytest.importorskip("prompt_toolkit")
    import asyncio

    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import ThreadedAutoSuggest
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    RIGHT = "\x1b[C"

    async def type_then(text, keys):
        with create_pipe_input() as inp:
            sess = PromptSession(completer=shell.make_completer(st),
                                 auto_suggest=ThreadedAutoSuggest(shell.make_suggester(st)),
                                 key_bindings=shell._make_keys(),
                                 complete_while_typing=True,
                                 input=inp, output=DummyOutput())
            task = asyncio.create_task(sess.prompt_async("> "))
            inp.send_text(text)
            await asyncio.sleep(0.8)      # the scan runs in a worker thread
            inp.send_text(keys)
            await asyncio.sleep(0.3)
            inp.send_text("\r")
            return await task

    async def main():
        assert await type_then("filter city = 'L", RIGHT) == "filter city = 'London'"
        assert await type_then("filter city = 'O", RIGHT) == "filter city = 'O''Brien Town'"
        # nothing suggested -> the arrow is just an arrow again
        assert await type_then("filter city = 'zz", RIGHT) == "filter city = 'zz'"

    asyncio.run(main())


def test_ghost_text_survives_a_backspace(st):
    """prompt_toolkit only asks the suggester after text is INSERTED, and any
    edit clears the current suggestion - so deleting a character left the line
    bare until you typed a new one. Backspacing is how you correct a wrong
    guess, which is precisely when you want the suggestion back.
    """
    pytest.importorskip("prompt_toolkit")
    import asyncio

    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import ThreadedAutoSuggest
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    st.column_values("city")

    async def main():
        with create_pipe_input() as inp:
            sess = PromptSession(completer=shell.make_completer(st),
                                 auto_suggest=ThreadedAutoSuggest(shell.make_suggester(st)),
                                 key_bindings=shell._make_keys(),
                                 complete_while_typing=True,
                                 input=inp, output=DummyOutput())
            shell._keep_suggesting_on_delete(sess.default_buffer)
            task = asyncio.create_task(sess.prompt_async("> "))
            inp.send_text("filter city = Lon")
            await asyncio.sleep(0.6)
            assert sess.app.current_buffer.suggestion.text == "don"
            inp.send_text("\x7f")                      # backspace
            await asyncio.sleep(0.6)
            got = sess.app.current_buffer.suggestion
            inp.send_text("\r")
            await task
            assert got is not None and got.text == "ndon"

    asyncio.run(main())


def test_ghost_text_works_from_a_cold_cache(st):
    """The first suggestion is the one that has to fetch, and it happens on a
    worker thread so the prompt keeps taking keys while it runs."""
    assert st._value_cache == {}
    assert suggestion_for(st, "filter city = 'L") == "ondon"
    assert st._value_cache                      # and it is cached for next time


def test_a_broken_pipeline_never_takes_the_prompt_down(st):
    """A completer that raises kills the shell. Ask for a column that isn't
    there and the answer is silence, not a traceback."""
    assert st.column_values("no_such_column") == ([], None)
    assert completions(st, "filter no_such_column = '") == []
