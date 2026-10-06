"""The settings of one presidio-agent run, set once from the command line.

The CLI parses `--base-url`, `--model`, `--out`, and `--private` and calls `use`. The
model client and the agent's tools read `current()`. Tau loads the extension as a
separate module, so the settings live here, in a module both copies import.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

DEFAULT_BASE_URL = "http://127.0.0.1:8080"  # llama-server's default address
DEFAULT_OUT = "/dev/shm/presidio-agent/out"
DEFAULT_PRIVATE = "/dev/shm/presidio-agent/private"


@dataclass(frozen=True)
class Settings:
    base_url: str = DEFAULT_BASE_URL  # the llama.cpp server, for the vision model and the agent
    model: str | None = None  # None: the model the server reports
    out: str = DEFAULT_OUT  # copies, page images, public answer keys
    private: str = DEFAULT_PRIVATE  # original personal data: never serve or share
    no_approval: bool = False  # run every tool without asking, for this session only
    approve_read_tools: bool = False  # ask before read-only tools too


_current = Settings()


def current() -> Settings:
    return _current


def use(settings: Settings) -> None:
    global _current  # noqa: PLW0603 -- one run has one set of settings, chosen on the command line
    _current = settings


def add_arguments(ap: argparse.ArgumentParser) -> None:
    """The options both commands share."""
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="the llama.cpp server (default: %(default)s)")
    ap.add_argument("--model", "-m", default=None, help="the model id; default: the one the server reports")
    ap.add_argument("--out", default=DEFAULT_OUT, help="folder for the copies (default: %(default)s)")
    ap.add_argument(
        "--private",
        default=DEFAULT_PRIVATE,
        help="folder for the original personal data; never serve or share it (default: %(default)s)",
    )


def add_agent_arguments(ap: argparse.ArgumentParser) -> None:
    """The agent's own options, after the shared ones."""
    add_arguments(ap)
    ap.add_argument("--no-approval", action="store_true", help="run every tool without asking, for this session")
    ap.add_argument("--approve-read-tools", action="store_true", help="ask before read-only tools too")


def from_arguments(a: argparse.Namespace) -> Settings:
    return replace(
        Settings(),
        base_url=a.base_url.rstrip("/"),
        model=a.model,
        out=a.out,
        private=a.private,
        no_approval=getattr(a, "no_approval", False),
        approve_read_tools=getattr(a, "approve_read_tools", False),
    )
