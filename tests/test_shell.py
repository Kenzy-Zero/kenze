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
