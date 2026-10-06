"""The tool approval gate: which tools ask, the dialog's three choices, and the saved setting."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from tau_coding.extensions import ToolCallHookEvent

from presidio_agent import approval, extension, recognizers, settings


class FakeUi:
    def __init__(self, choice: str | None, has_ui: bool = True) -> None:
        self.choice = choice
        self.has_ui = has_ui
        self.asked: list[tuple[str, list[str]]] = []
        self.notes: list[tuple[str, str]] = []

    async def select(self, title: str, options: list[str]) -> str | None:
        self.asked.append((title, options))
        return self.choice

    def notify(self, message: str, level: str = "info") -> None:
        self.notes.append((message, level))


class FakeContext:
    def __init__(self, ui: FakeUi) -> None:
        self.ui = ui


def call(gate: approval.Gate, tool: str, ui: FakeUi, arguments: dict[str, Any] | None = None) -> Any:
    return asyncio.run(gate.on_tool_call(ToolCallHookEvent(tool, arguments or {}), FakeContext(ui)))


def test_read_only_and_own_tools_run_without_a_dialog():
    gate = approval.Gate("ask")
    for tool in ("read", "grep", "find", "ls", "find_personal_values", "accept_value", "make_copies"):
        assert not gate.needs_approval(tool), tool
    for tool in ("bash", "write", "edit", "some_new_tool"):
        assert gate.needs_approval(tool), tool
    assert approval.Gate("ask", ask_read_tools=True).needs_approval("read")
    assert not approval.Gate("ask", ask_read_tools=True).needs_approval("make_copies")
    assert not approval.Gate("allow").needs_approval("bash")


def test_allow_once_runs_the_call_and_keeps_asking():
    gate, ui = approval.Gate("ask"), FakeUi(approval.ALLOW_ONCE)
    assert call(gate, "bash", ui, {"command": "ls"}) is None
    assert call(gate, "bash", ui, {"command": "ls"}) is None
    assert len(ui.asked) == 2
    title, options = ui.asked[0]
    assert title == 'Allow bash? {"command": "ls"}' and options == list(approval.CHOICES)


def test_allow_all_stops_asking_for_this_session():
    gate, ui = approval.Gate("ask"), FakeUi(approval.ALLOW_SESSION)
    assert call(gate, "write", ui) is None and call(gate, "edit", ui) is None
    assert len(ui.asked) == 1 and gate.session_allowed


@pytest.mark.parametrize("choice", [approval.DENY, None])
def test_deny_or_escape_blocks_and_tells_the_model_to_stop(choice):
    result = call(approval.Gate("ask"), "bash", FakeUi(choice), {"command": "rm -rf out"})
    assert result.block and "did not run" in result.reason and "Stop here" in result.reason


def test_without_a_ui_gated_calls_are_blocked():
    ui = FakeUi(approval.ALLOW_ONCE, has_ui=False)
    result = call(approval.Gate("ask"), "bash", ui)
    assert result.block and "non-interactive" in result.reason and ui.asked == []
    no_context = asyncio.run(approval.Gate("ask").on_tool_call(ToolCallHookEvent("bash", {}), None))
    assert no_context is not None and no_context.block
    assert asyncio.run(approval.Gate("ask").on_tool_call(object(), None)) is None


def test_long_input_is_shortened_in_the_dialog():
    title = approval.describe("write", {"content": "x" * 1000})
    assert len(title) < approval.INPUT_CHARS + 20 and title.endswith("…")


def test_the_permission_is_saved_and_read_back(tmp_path):
    private = str(tmp_path / "private")
    assert approval.saved_permission(private) is None
    assert approval.startup_permission(False, private) == "ask"
    gate = approval.Gate("ask", session_allowed=True)
    handle = approval.approval_command(private, gate)
    assert handle("", None) == "permission: ask. Use /approval ask or /approval allow."
    assert handle("off", None) == "permission: allow, for this and new sessions"
    assert gate.permission == "allow" and not gate.session_allowed
    assert approval.saved_permission(private) == "allow" and approval.startup_permission(False, private) == "allow"
    assert "unknown setting 'maybe'" in handle("maybe", None)
    assert handle("ON", None) == "permission: ask, for this and new sessions"
    assert json.loads((tmp_path / "private" / "settings.json").read_text()) == {"permission": "ask"}


def test_no_approval_wins_and_bad_settings_are_ignored(tmp_path):
    (tmp_path / "settings.json").write_text('{"permission": "ask", "other": 1}')
    assert approval.startup_permission(True, str(tmp_path)) == "allow"
    approval.save_permission(str(tmp_path), "allow")
    assert json.loads((tmp_path / "settings.json").read_text()) == {"permission": "allow", "other": 1}
    (tmp_path / "settings.json").write_text("[1]")
    assert approval.saved_permission(str(tmp_path)) is None
    approval.save_permission(str(tmp_path), "ask")
    assert approval.saved_permission(str(tmp_path)) == "ask"
    (tmp_path / "settings.json").write_text('{"permission": "sometimes"}')
    assert approval.saved_permission(str(tmp_path)) is None


def test_the_extension_installs_the_gate_command_and_notice(monkeypatch, tmp_path):
    settings.use(settings.Settings(private=str(tmp_path), no_approval=True))
    monkeypatch.setattr(recognizers, "analyzer", lambda: None)

    class Api:
        def __init__(self) -> None:
            self.hooks: dict[str, Any] = {}
            self.commands: dict[str, Any] = {}

        def register_tool(self, tool: Any) -> None:
            pass

        def on(self, event: str, handler: Any) -> None:
            self.hooks[event] = handler

        def register_command(self, name: str, handler: Any, *, description: str, usage: str) -> None:
            self.commands[name] = (handler, usage)

    api = Api()
    try:
        extension.setup(api)
    finally:
        settings.use(settings.Settings())
    assert set(api.hooks) == {"tool_call", "session_start"} and api.commands["approval"][1] == "/approval [ask|allow]"
    ui = FakeUi(None)
    api.hooks["session_start"](object(), FakeContext(ui))
    assert ui.notes == [("permission: allow (tools run without asking)", "warning")]
    assert asyncio.run(api.hooks["tool_call"](ToolCallHookEvent("bash", {}), FakeContext(ui))) is None
    api.commands["approval"][0]("ask", None)
    quiet = FakeUi(None)
    api.hooks["session_start"](object(), FakeContext(quiet))
    assert quiet.notes == []
