"""Start Tau as presidio-agent: Tau's own CLI with this package's extension and policy.

The model server is llama.cpp's, at `PRESIDIO_AGENT_VL`, the same one the tools use for
reading pages. Tau's state, including its session logs, goes to a `tau` folder inside the
private folder, because the tools' reports contain original personal data.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

from presidio_agent import extension, vl

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
        if model and not has_option(args, "--model", "-m"):
            out += ["--model", model]
    return [*out, *args]


def tau_env(env: Mapping[str, str]) -> dict[str, str]:
    """The environment for Tau: llama.cpp at the tools' server, Tau's state in the private folder."""
    private = env.get(extension.PRIVATE_ENV, extension.DEFAULT_PRIVATE)
    return {
        "LLAMA_BASE_URL": env.get("LLAMA_BASE_URL", vl.BASE),
        "TAU_HOME": env.get("TAU_HOME", os.path.join(private, "tau")),
        extension.PRIVATE_ENV: private,
        extension.OUT_ENV: env.get(extension.OUT_ENV, extension.DEFAULT_OUT),
    }


def server_problem(base: str, timeout: float = 5) -> str | None:
    """Why the llama.cpp server at `base` cannot be used, or None when it answers."""
    try:
        with urllib.request.urlopen(base + "/health", timeout=timeout) as response:
            return None if response.status == 200 else f"it answered {response.status}"
    except (OSError, ValueError) as exc:
        return str(getattr(exc, "reason", exc))


def run(args: Sequence[str]) -> None:
    """Hand this process to Tau's CLI; Tau exits the process when it is done."""
    from tau_coding.cli import app  # noqa: PLC0415 -- the TUI loads only when the agent starts

    env = tau_env(os.environ)
    if not has_option(args, "--provider") and (problem := server_problem(env["LLAMA_BASE_URL"])):
        sys.exit(
            f"presidio-agent: no llama.cpp server at {env['LLAMA_BASE_URL']} ({problem}). Start llama-server "
            f"with a vision model and its --mmproj, and set {vl.BASE_ENV} to its address."
        )
    os.environ.update(env)
    os.makedirs(os.environ["TAU_HOME"], exist_ok=True)
    app(args=tau_args(args, vl.model()), prog_name="presidio-agent")
