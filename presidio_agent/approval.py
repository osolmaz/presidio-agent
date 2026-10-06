"""The tool approval gate, after localpi's.

Approval is on by default. Before a tool runs, a dialog shows its name and input with
three choices: allow once, allow all tools for this session, or deny and stop. A denied
call does not run, and the model is told so and told to stop. Read-only tools and
presidio-agent's own tools run without a dialog: the own tools only read the documents
and write to the output and private folders. `bash`, the tools that write files, and
any unknown tool ask. Without an interactive UI nobody can approve, so those calls are
blocked.

`--no-approval` turns the gate off for one session, and `/approval allow|ask` changes
the saved setting for new sessions. `--approve-read-tools` puts read-only tools behind
the gate too.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from tau_agent.types import JSONValue
from tau_coding.extensions import ToolCallHookEvent, ToolCallHookResult

Permission = Literal["ask", "allow"]
READ_ONLY_TOOLS = frozenset({"read", "grep", "find", "ls"})
OWN_TOOLS = frozenset({"find_personal_values", "accept_value", "make_copies"})
ALLOW_ONCE = "Allow once"
ALLOW_SESSION = "Allow all tools for this session"
DENY = "Deny and stop"
CHOICES = (ALLOW_ONCE, ALLOW_SESSION, DENY)
ALIASES: dict[str, Permission] = {"ask": "ask", "on": "ask", "allow": "allow", "off": "allow"}
DENIED = (
    "the user denied this call, so it did not run. Stop here and ask the user what to do; "
    "do not try to reach the same result another way."
)
NO_UI = (
    "nobody is there to approve it in a non-interactive run, so it did not run. "
    "Stop; the user can start presidio-agent interactively or with --no-approval."
)
INPUT_CHARS = 400


class Ui(Protocol):
    @property
    def has_ui(self) -> bool: ...

    def select(self, title: str, options: Sequence[str]) -> Awaitable[str | None]: ...


class Context(Protocol):
    @property
    def ui(self) -> Ui: ...


def settings_path(private: str) -> str:
    """The saved permission lives with presidio-agent's other state, in the private folder."""
    return os.path.join(private, "settings.json")


def saved_permission(private: str) -> Permission | None:
    try:
        with open(settings_path(private), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    value = data.get("permission") if isinstance(data, dict) else None
    return ALIASES.get(value) if isinstance(value, str) else None


def save_permission(private: str, permission: Permission) -> None:
    os.makedirs(private, exist_ok=True)
    path = settings_path(private)
    data: dict[str, object] = {}
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        data = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        pass
    data["permission"] = permission
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def describe(tool: str, arguments: Mapping[str, JSONValue]) -> str:
    """The dialog's title: the tool and its input, shortened."""
    shown = json.dumps(dict(arguments), ensure_ascii=False)
    if len(shown) > INPUT_CHARS:
        shown = shown[: INPUT_CHARS - 1] + "…"
    return f"Allow {tool}? {shown}"


@dataclass
class Gate:
    permission: Permission
    ask_read_tools: bool = False
    session_allowed: bool = False

    def needs_approval(self, tool: str) -> bool:
        if self.permission == "allow" or self.session_allowed or tool in OWN_TOOLS:
            return False
        return self.ask_read_tools or tool not in READ_ONLY_TOOLS

    async def on_tool_call(self, event: object, context: object = None) -> ToolCallHookResult | None:
        """Tau's `tool_call` hook: ask before a gated tool runs, and block it unless allowed."""
        if not isinstance(event, ToolCallHookEvent) or not self.needs_approval(event.tool_name):
            return None
        ui = getattr(context, "ui", None)
        if ui is None or not ui.has_ui:
            return ToolCallHookResult(block=True, reason=NO_UI)
        choice = await ui.select(describe(event.tool_name, event.arguments), list(CHOICES))
        if choice == ALLOW_SESSION:
            self.session_allowed = True
        if choice in (ALLOW_ONCE, ALLOW_SESSION):
            return None
        return ToolCallHookResult(block=True, reason=DENIED)


def approval_command(private: str, gate: Gate) -> Callable[[str, object], str]:
    """`/approval [ask|allow]`: show the permission, or change it for this and new sessions."""

    def handle(args: str, context: object = None) -> str:
        word = args.strip().lower()
        if not word:
            return f"permission: {gate.permission}. Use /approval ask or /approval allow."
        permission = ALIASES.get(word)
        if permission is None:
            return f"unknown setting {word!r}; use ask, allow, on, or off"
        gate.permission = permission
        gate.session_allowed = False
        save_permission(private, permission)
        return f"permission: {permission}, for this and new sessions"

    return handle


def startup_permission(no_approval: bool, private: str) -> Permission:
    """--no-approval first, then the saved setting, then ask."""
    if no_approval:
        return "allow"
    return saved_permission(private) or "ask"
