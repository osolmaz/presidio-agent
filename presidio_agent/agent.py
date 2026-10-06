"""Start Tau as presidio-agent: Tau's own CLI with this package's extension and policy.

The agent and the tools use the same llama.cpp server. Tau's llama.cpp backend takes
its address only from `LLAMA_BASE_URL`, so the launcher sets that for the Tau process
it starts. Tau's state, including its session logs, goes to a `tau` folder inside the
private folder, because the tools' reports contain original personal data.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from presidio_agent import settings, vl

PACKAGE = Path(__file__).parent
EXTENSION = PACKAGE / "extension.py"
POLICY = PACKAGE / "agent.md"


def has_option(args: Sequence[str], *names: str) -> bool:
    """Whether `args` sets one of the options, as `--name value` or `--name=value`."""
    return any(a == n or a.startswith(n + "=") for a in args for n in names)


def tau_args(args: Sequence[str], model: str | None) -> list[str]:
    """Tau's arguments: the extension and the policy, then llama.cpp unless the caller chose a provider."""
    out = ["--extension", str(EXTENSION), "--append-system-prompt", str(POLICY)]
    if not has_option(args, "--provider"):
        out += ["--provider", "llama.cpp"]
        if model:
            out += ["--model", model]
    return [*out, *args]


def tau_env(chosen: settings.Settings) -> dict[str, str]:
    """What Tau's own code reads: the llama.cpp address, and its state folder inside the private folder."""
    return {"LLAMA_BASE_URL": chosen.base_url, "TAU_HOME": os.path.join(chosen.private, "tau")}


def server_problem(base_url: str, timeout: float = 5) -> str | None:
    """Why the llama.cpp server at `base_url` cannot be used, or None when it answers."""
    try:
        with urllib.request.urlopen(base_url + "/health", timeout=timeout) as response:
            return None if response.status == 200 else f"it answered {response.status}"
    except (OSError, ValueError) as exc:
        return str(getattr(exc, "reason", exc))


def run(chosen: settings.Settings, args: Sequence[str]) -> None:
    """Hand this process to Tau's CLI with the chosen settings; Tau exits the process when it is done."""
    from tau_coding.cli import app  # noqa: PLC0415 -- the TUI loads only when the agent starts

    settings.use(chosen)
    if not has_option(args, "--provider") and (problem := server_problem(chosen.base_url)):
        sys.exit(
            f"presidio-agent: no llama.cpp server at {chosen.base_url} ({problem}). Start llama-server "
            "with a vision model and its --mmproj, or pass --base-url with its address."
        )
    env = tau_env(chosen)
    os.environ.update(env)
    os.makedirs(env["TAU_HOME"], exist_ok=True)
    app(args=tau_args(args, vl.model()), prog_name="presidio-agent")
