"""Shell command-parity guards: every command listed in the menu/help has a
handler (and the CLI's file-writing commands are reachable in the shell)."""
from __future__ import annotations

import pytest

from kenze import shell


def test_every_listed_command_has_a_handler():
    listed = set(shell.COMMANDS)
    handled = set(shell.HANDLERS) | {"exit", "quit", "q"}   # exit is dispatched specially
    missing = listed - handled
    assert not missing, f"listed in the menu but no handler: {missing}"


def test_every_listed_command_is_in_a_known_group():
    known = {g for g, _ in shell.GROUPS}
    for name, (group, _desc) in shell.COMMANDS.items():
        assert group in known, f"{name} is in unknown group {group}"


def test_convert_is_in_the_shell():
    # 0.8.3 regression guard: convert used to be CLI-only (Ken hit this live)
    assert "convert" in shell.COMMANDS
    assert "convert" in shell.HANDLERS
    assert "convert" in shell.FILE_CMDS      # gets file-path autocomplete


def test_guide_hint_states():
    gh = shell._guide_hint
    assert gh("", False)[0] == "start"                 # no file yet
    assert gh("", True)[0] == "flow"                   # file loaded, empty line
    assert gh("peek", True)[0] == "ready"              # ready-on-Enter command
    kind, msg = gh("filter", True)                     # needs an argument
    assert kind == "need" and "condition" in msg
    assert gh("filter amount > 0", True)[0] == "ready"
    kind, msg = gh("convert", True)                    # needs output + example
    assert kind == "need" and "convert out.geojson" in msg
    kind, msg = gh("convert out.geojson", True)        # ready + optional opts shown
    assert kind == "ready" and "geom=" in msg
    assert gh("/peek", True)[0] == "ready"             # slash prefix handled
    assert gh("frobnicate", True) is None              # unknown command -> no hint


def test_every_command_has_a_next_step_hint():
    # every menu command should give "what to type next" guidance
    for name in shell.COMMANDS:
        assert name in shell.CMD_GUIDE or name in shell.READY_ON_ENTER, \
            f"{name} has no next-step hint (add it to CMD_GUIDE or READY_ON_ENTER)"


# --- session settings ----------------------------------------------------------

SETTINGS = ["memory", "threads", "temp", "disk-check", "skip-bad", "strict-csv"]


def test_every_setting_is_discoverable():
    """A setting the shell accepts but never offers is a setting nobody finds.

    0.9.6 regression guard: `set strict-csv off` worked from the day it was
    written, but was missing from both the autocomplete list and the menu
    description - so the only way to learn it existed was to read the source.
    Adding a setting means adding it here too, on purpose.
    """
    assert shell.CMD_GUIDE["set"][3] == SETTINGS
    described = shell.COMMANDS["set"][1]
    for name in SETTINGS:
        assert name in described, f"`set` menu text doesn't mention {name}"


def test_every_offered_setting_is_actually_handled(capsys):
    """...and the reverse: nothing is offered that the handler would reject."""
    st = shell.ShellState()
    for name in shell.CMD_GUIDE["set"][3]:
        shell.dispatch(st, f"set {name} off")
        out = capsys.readouterr().out
        assert "set what?" not in out, f"`set {name}` is offered but not handled"


# --- quote auto-closing (0.9.5) ------------------------------------------------
# Requested by a user typing text filters in the shell: opening a quote should
# add the closing one and leave the cursor between them.

def test_quote_action_rules():
    qa = shell._quote_action
    # the ask: an opening quote closes itself
    assert qa("filter city = ", 14, "'") == "pair"
    assert qa("", 0, "'") == "pair"
    assert qa("load ", 5, '"') == "pair"
    # typing the closing quote steps over the one already there
    assert qa("filter city = ''", 15, "'") == "skip"
    # an apostrophe inside a word is never doubled (don't, O'Brien)
    assert qa("don", 3, "'") == "plain"
    # a quote typed in front of existing text doesn't wrap it
    assert qa("filter city = X", 14, "'") == "plain"
    # non-quote characters are none of our business
    assert qa("filter city = ", 14, "x") == "plain"


def test_wordish_handles_end_of_line():
    # "" in "_" is True in Python - that bug made an end-of-line quote refuse to
    # pair, which is the single most common place you type one.
    assert shell._wordish("") is False
    assert shell._wordish("a") is True
    assert shell._wordish("_") is True
    assert shell._wordish(" ") is False


def test_closes_empty_pair():
    assert shell._closes_empty_pair("filter city = ''", 15) is True
    assert shell._closes_empty_pair("filter city = 'a'", 15) is False
    assert shell._closes_empty_pair("", 0) is False


def test_typing_a_quoted_filter_end_to_end():
    """Drive the real key bindings against a real prompt_toolkit buffer."""
    ptk_buffer = pytest.importorskip("prompt_toolkit.buffer")

    handlers = {str(b.keys[0]): b.handler for b in shell._make_keys().bindings}

    class _Event:
        def __init__(self, buf):
            self.current_buffer = buf

    def typed(keys):
        buf = ptk_buffer.Buffer()
        for k in keys:
            if k in ("'", '"'):
                handlers[k](_Event(buf))
            elif k == "<backspace>":
                handlers["Keys.ControlH"](_Event(buf))
            else:
                buf.insert_text(k)
        return buf.text, buf.cursor_position

    # opening a quote closes it and parks the cursor inside
    assert typed(list("filter city = ") + ["'"]) == ("filter city = ''", 15)
    # ...so the whole condition can be typed straight through
    assert typed(list("filter city = ") + ["'"] + list("London") + ["'"]) == (
        "filter city = 'London'", 22)
    # backspacing the opening quote takes the auto-added closing one with it
    assert typed(list("filter city = ") + ["'", "<backspace>"]) == ("filter city = ", 14)
    # double quotes work the same, which is how paths with spaces get typed
    assert typed(list("load ") + ['"'] + list("Feb 10.csv") + ['"']) == (
        'load "Feb 10.csv"', 17)
    # an apostrophe mid-word inserts ONE quote, not a pair
    assert typed(list("sql select 'don") + ["'"])[0] == "sql select 'don'"
    # a line with no quotes is completely unaffected
    assert typed(list("filter amount > 100")) == ("filter amount > 100", 19)
