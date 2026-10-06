"""The Tau extension: the agent's tools, backed by `tools.Session`.

Tau loads this module with `-e` and calls `setup(tau)`. Each tool runs the fixed,
tested flow in a worker thread and returns its JSON report to the model; the model
decides what to look at, which candidates to accept, and when the copies are done.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Protocol

from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult, ToolCancellationToken, ToolUpdateCallback
from tau_agent.types import JSONValue

from presidio_agent import detect, recognizers, settings
from presidio_agent.pipeline import Workspace
from presidio_agent.tools import Report, Session

Run = Callable[[Mapping[str, JSONValue]], Report]


PATH: dict[str, JSONValue] = {"type": "string", "description": "path of the document: an image or a PDF"}


def workspace() -> Workspace:
    chosen = settings.current()
    return Workspace(chosen.out, chosen.private)


def _int(arguments: Mapping[str, JSONValue], name: str, default: int) -> int:
    value = arguments.get(name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _str(arguments: Mapping[str, JSONValue], name: str) -> str:
    value = arguments.get(name)
    return value if isinstance(value, str) else ""


def tool(name: str, description: str, properties: dict[str, JSONValue], required: list[str], run: Run) -> AgentTool:
    """A Tau tool whose blocking `run` goes to a worker thread and whose report goes back as JSON."""

    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        try:
            report = await asyncio.to_thread(run, arguments)
        except (OSError, ValueError, RuntimeError) as exc:
            report = {"error": f"{type(exc).__name__}: {exc}"}
        return AgentToolResult(content=[TextContent(text=json.dumps(report, ensure_ascii=False))])

    schema: dict[str, JSONValue] = {"type": "object", "properties": properties, "required": list(required)}
    return AgentTool(
        name=name,
        label=name.replace("_", " ").capitalize(),
        description=description,
        parameters=schema,
        execute_fn=execute,
        execution_mode="sequential",
    )


def agent_tools(session: Session) -> list[AgentTool]:
    return [
        tool(
            "find_personal_values",
            "Find the personal values in a document. The vision model reads each page and checks the "
            "candidates Presidio flagged in the page's text. Reports every value with its type, owner, "
            "and whether it was located, the candidates the model did not confirm, and the page images.",
            {"path": PATH},
            ["path"],
            lambda a: session.analyse(_str(a, "path")),
        ),
        tool(
            "accept_value",
            "Add a value that you decided is personal data, such as an unconfirmed Presidio candidate "
            "that the page image shows is a person's name. Reports whether it was located on the page.",
            {
                "path": PATH,
                "page": {"type": "integer", "description": "page number, from 1"},
                "text": {"type": "string", "description": "the value exactly as printed"},
                "type": {"type": "string", "enum": list(detect.TYPES)},
                "owner": {"type": "string", "description": "whose value it is: customer, manager, payment, ..."},
            },
            ["path", "page", "text", "type", "owner"],
            lambda a: session.accept(
                _str(a, "path"), _int(a, "page", 0), _str(a, "text"), _str(a, "type"), _str(a, "owner") or "customer"
            ),
        ),
        tool(
            "make_copies",
            "Make synthetic copies with every located value replaced by a consistent invented one. Each "
            "copy is read back and checked for surviving original values; use only copies that pass.",
            {
                "path": PATH,
                "n": {"type": "integer", "description": "number of copies", "default": 1},
                "seed": {"type": "integer", "description": "seed of the first copy", "default": 1},
            },
            ["path"],
            lambda a: session.copies(_str(a, "path"), _int(a, "n", 1), _int(a, "seed", 1)),
        ),
    ]


class _Api(Protocol):
    """The part of Tau's extension API this module uses."""

    def register_tool(self, tool: AgentTool) -> None: ...


def setup(tau: _Api) -> None:
    """Tau's entry point: register the tools over one session's documents."""
    session = Session(workspace(), recognizers.analyzer())
    for agent_tool in agent_tools(session):
        tau.register_tool(agent_tool)
