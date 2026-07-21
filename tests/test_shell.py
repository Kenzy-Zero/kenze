"""Shell command-parity guards: every command listed in the menu/help has a
handler (and the CLI's file-writing commands are reachable in the shell)."""
from __future__ import annotations

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
