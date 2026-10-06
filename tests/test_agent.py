"""Presidio's candidates, the shared pipeline, the agent's tools, and the Tau launcher."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import tau_coding.cli
from PIL import Image

from presidio_agent import agent, candidates, cli, detect, extension, locate, ocr, pipeline, recognizers, source, vl
from presidio_agent.candidates import Candidate
from presidio_agent.detect import Value
from presidio_agent.locate import Located
from presidio_agent.tools import Session

TEXT = "Kunde: Leon Hartmann\nIBAN DE89 3704 0044 0532 0130 00\nGeschäftsführer: Markus Weber"


def as_json(report: object) -> Any:
    """A tool report as the model receives it."""
    return json.loads(json.dumps(report))


def spans_for(text: str, *flags: tuple[str, str, float]) -> list[tuple[int, int, str, float]]:
    return [(text.index(t), text.index(t) + len(t), entity, score) for t, entity, score in flags]


# --- candidates ------------------------------------------------------------


def test_candidates_keep_checkable_entities_once_with_normalised_spaces():
    text = "Leon  Hartmann, Leon  Hartmann, Berlin, Bank AG, ab"
    spans = [
        (0, 14, "PERSON", 0.85),
        (16, 30, "PERSON", 0.85),  # the same flag again
        (32, 38, "LOCATION", 0.85),  # not checked: places are mostly the business's own
        (40, 47, "PERSON", 0.3),  # below the score floor
        (49, 51, "PERSON", 0.9),  # a fragment
    ]
    assert candidates.from_spans(text, spans) == [Candidate("Leon Hartmann", "PERSON", 0.85)]


def test_candidates_score_floor_is_inclusive_and_rounded():
    text = "Markus Weber"
    assert candidates.from_spans(text, [(0, 12, "PERSON", 0.4)]) == [Candidate("Markus Weber", "PERSON", 0.4)]
    assert candidates.from_spans(text, [(0, 12, "PERSON", 0.8567)])[0].score == 0.86
    assert candidates.from_spans("abc", [(0, 3, "PERSON", 0.9)]) == [Candidate("abc", "PERSON", 0.9)]


def test_find_needs_presidio_and_text():
    def analyze(text: str) -> list[tuple[int, int, str, float]]:
        return spans_for(text, ("Markus Weber", "PERSON", 0.85))

    assert candidates.find(TEXT, None) == []
    assert candidates.find("  \n", analyze) == []
    assert candidates.find(TEXT, analyze) == [Candidate("Markus Weber", "PERSON", 0.85)]


def test_value_types_for_entities():
    assert candidates.value_type("PERSON") == "person"
    assert candidates.value_type("IBAN_CODE") == "iban"
    assert candidates.value_type("CREDIT_CARD") == "card"
    assert candidates.value_type("DE_TAX_ID") == "id"


def test_a_candidate_is_covered_by_a_value_either_way():
    assert candidates.covered("Leon Hartmann", "LEON HARTMANN")
    assert candidates.covered("Hartmann", "Herr Leon Hartmann")
    assert candidates.covered("Tel. 030 555-014", "030 555014")
    assert not candidates.covered("Markus Weber", "Leon Hartmann")
    assert not candidates.covered("", "Leon Hartmann") and not candidates.covered("Leon", "--")


def test_unconfirmed_candidates_are_those_no_value_covers():
    found = [Candidate("Leon Hartmann", "PERSON", 0.85), Candidate("Markus Weber", "PERSON", 0.85)]
    assert candidates.unconfirmed(found, iter(["LEON HARTMANN"])) == [found[1]]
    assert candidates.unconfirmed(found, []) == found


def test_recognizers_find_german_invoice_candidates():
    analyze = recognizers.analyzer()
    flagged = {(c.text, c.entity) for c in candidates.find(TEXT, analyze)}
    assert ("DE89 3704 0044 0532 0130 00", "IBAN_CODE") in flagged
    assert ("Markus Weber", "PERSON") in flagged


# --- detection prompt ----------------------------------------------------------


def test_review_prompt_lists_found_values_and_presidio_candidates():
    found = [Value("Leon Hartmann", "person", "customer", (0, 0, 1, 1))]
    with_flags = detect.review_prompt(found, "OCR TEXT", ["Markus Weber"])
    assert "- person: Leon Hartmann" in with_flags and "OCR TEXT" in with_flags
    assert "rule-based detector" in with_flags and "- Markus Weber" in with_flags
    plain = detect.review_prompt([], "OCR TEXT")
    assert "(none)" in plain and "rule-based detector" not in plain


def test_find_values_passes_candidates_to_the_second_pass(monkeypatch):
    asked: list[str] = []

    def chat(content, max_tokens=4096):
        asked.append(content[-1]["text"])
        return "[]"

    monkeypatch.setattr(vl, "chat", chat)
    assert detect.find_values(Image.new("RGB", (100, 100), "white"), "ocr", ["Markus Weber"]) == []
    assert "Markus Weber" not in asked[0] and "- Markus Weber" in asked[1]


# --- pipeline and tools -----------------------------------------------------------

WEBER = Value("Markus Weber", "person", "manager", (0, 0, 200, 40))
HARTMANN = Value("Leon Hartmann", "person", "customer", (0, 0, 200, 40))


def place(value: Value) -> Located:
    return Located(value, (10, 10, 200, 30), (60, 10, 200, 30), None, "ocr", value.text)


def text_page() -> source.Page:
    words = [ocr.Word(w, (10 + 60 * i, 10, 60 + 60 * i, 30)) for i, w in enumerate(TEXT.split())]
    return source.Page(Image.new("RGB", (600, 200), "white"), [ocr.Line(tuple(words))], "text")


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """One text page; the model finds the customer only; locate finds every value Markus Weber or Leon Hartmann."""
    calls: dict[str, Any] = {"detect": [], "locate": 0}

    def find_values(img, text, flagged=()):
        calls["detect"].append(list(flagged))
        return [HARTMANN]

    def locate_values(img, values, lines, read, line_ocr):
        calls["locate"] += 1
        return [[place(v)] if v.text in TEXT else [] for v in values]

    monkeypatch.setattr(source, "load", lambda path, dpi=150: [text_page()])
    monkeypatch.setattr(detect, "find_values", find_values)
    monkeypatch.setattr(locate, "locate", locate_values)
    monkeypatch.setattr(vl, "read_text", lambda img: "")
    monkeypatch.setattr(vl, "read_page", lambda img: "Kunde: IBAN")
    ws = pipeline.Workspace(str(tmp_path / "out"), str(tmp_path / "private"))
    return ws, calls


def analyze(text: str) -> list[tuple[int, int, str, float]]:
    return spans_for(text, ("Leon Hartmann", "PERSON", 0.85), ("Markus Weber", "PERSON", 0.85))


def test_analyse_document_checks_candidates_and_caches_privately(fakes, tmp_path):
    ws, calls = fakes
    doc = pipeline.analyse_document(str(tmp_path / "invoice.pdf"), ws, analyze)
    again = pipeline.analyse_document(str(tmp_path / "invoice.pdf"), ws, None)  # read from the caches
    assert calls["detect"] == [["Leon Hartmann", "Markus Weber"]] and calls["locate"] == 1
    assert [c.text for c in again.pages[0].unconfirmed()] == ["Markus Weber"]
    assert doc.pages[0].summary() == (
        "page 1 (text): 1 personal values, 1 located in 1 places (1 by OCR, 0 by pixels), "
        "1 of 2 Presidio candidates not confirmed"
    )
    cached = (tmp_path / "private" / "invoice.p1.candidates.json").read_text(encoding="utf-8")
    assert "Markus Weber" in cached
    assert (tmp_path / "out" / "invoice.p1.boxes.png").exists()


def test_session_reports_values_candidates_and_images(fakes, tmp_path):
    ws, _ = fakes
    report = as_json(Session(ws, analyze).analyse(str(tmp_path / "invoice.pdf")))
    page = report["pages"][0]
    assert page["values"] == [{"text": "Leon Hartmann", "type": "person", "owner": "customer", "located": True}]
    assert page["unconfirmed_candidates"] == [
        {"text": "Markus Weber", "entity": "PERSON", "score": 0.85, "suggested_type": "person"}
    ]
    assert page["image"].endswith("invoice.p1.original.png") and page["kind"] == "text"


def test_accepting_a_candidate_locates_it_and_updates_the_cache(fakes, tmp_path):
    ws, calls = fakes
    session = Session(ws, analyze)
    path = str(tmp_path / "invoice.pdf")
    assert session.accept(path, 1, "Markus Weber", "person", "manager") == {
        "accepted": "Markus Weber",
        "page": 1,
        "located": True,
    }
    assert as_json(session.accept(path, 1, "Nobody Here", "person", "manager"))["located"] is False
    assert as_json(session.analyse(path))["pages"][0]["unconfirmed_candidates"] == []
    reloaded = pipeline.analyse_document(path, ws, None)
    assert [v.text for v in reloaded.pages[0].analysed.values] == ["Leon Hartmann", "Markus Weber", "Nobody Here"]
    assert calls["locate"] == 3


def test_accept_rejects_a_missing_page_or_an_unknown_type(fakes, tmp_path):
    ws, _ = fakes
    session = Session(ws, analyze)
    path = str(tmp_path / "invoice.pdf")
    assert "page 2 does not exist" in str(session.accept(path, 2, "Markus Weber", "person", "manager")["error"])
    assert "page 0 does not exist" in str(session.accept(path, 0, "Markus Weber", "person", "manager")["error"])
    assert "not one of" in str(session.accept(path, 1, "Markus Weber", "manager", "manager")["error"])


def test_copies_report_their_files_and_leak_checks(fakes, tmp_path):
    ws, _ = fakes
    report = as_json(Session(ws, analyze).copies(str(tmp_path / "invoice.pdf"), 2, 7))
    first, second = report["copies"]
    assert first["pdf"].endswith("invoice.copy-1.pdf") and first["key"].endswith("invoice.copy-1.json")
    assert first["leak_check_passed"] is True and second["summary"].startswith("copy 2: 1 values replaced")
    public = (tmp_path / "out" / "invoice.copy-1.json").read_text(encoding="utf-8")
    assert "Hartmann" not in public
    assert "Hartmann" in (tmp_path / "private" / "invoice.copy-1.private.json").read_text(encoding="utf-8")


def test_a_copy_without_a_leak_check_does_not_pass(fakes, tmp_path):
    ws, _ = fakes
    doc = pipeline.analyse_document(str(tmp_path / "invoice.pdf"), ws, None)
    result = pipeline.make_copies(doc, ws, 1, 1, verify=False, leak_check=False)[0]
    assert "leak_check" not in result.key["pages"][0]
    assert pipeline.copy_summary(1, result.key, verified=False).endswith("read-back skipped, 0 barcodes scrambled, ")


def test_copy_command_runs_the_flow_with_presidio(fakes, tmp_path, monkeypatch, capsys):
    ws, calls = fakes
    monkeypatch.setattr(recognizers, "analyzer", lambda: analyze)
    cli.main(["copy", str(tmp_path / "invoice.pdf"), "--n", "1", "--out", ws.out, "--private", ws.private])
    printed = capsys.readouterr().out
    assert "1 of 2 Presidio candidates not confirmed" in printed and "copy 1: 1 values replaced" in printed
    assert calls["detect"] == [["Leon Hartmann", "Markus Weber"]]


# --- the Tau extension ------------------------------------------------------------


def test_tools_run_in_a_thread_and_report_json_or_the_error():
    def run(arguments):
        if arguments.get("fail"):
            raise ValueError("bad document")
        return {"echo": arguments.get("path"), "page": extension._int(arguments, "page", 1)}

    tool = extension.tool("echo_tool", "Echo.", {"path": extension.PATH}, ["path"], run)
    assert tool.label == "Echo tool" and tool.parameters["required"] == ["path"]
    assert tool.execution_mode == "sequential"
    ok = asyncio.run(tool.execute("1", {"path": "a.pdf", "page": 3}))
    assert json.loads(ok.text) == {"echo": "a.pdf", "page": 3}
    failed = asyncio.run(tool.execute("2", {"path": "a.pdf", "fail": True}))
    assert json.loads(failed.text) == {"error": "ValueError: bad document"}


def test_argument_readers_fall_back_on_wrong_types():
    assert extension._int({"n": "2"}, "n", 1) == 1 and extension._int({"n": True}, "n", 1) == 1
    assert extension._int({"n": 4}, "n", 1) == 4
    assert extension._str({"path": 3}, "path") == "" and extension._str({"path": "a"}, "path") == "a"


def test_setup_registers_the_three_tools(monkeypatch, fakes, tmp_path):
    ws, _ = fakes
    monkeypatch.setenv(extension.OUT_ENV, ws.out)
    monkeypatch.setenv(extension.PRIVATE_ENV, ws.private)
    monkeypatch.setattr(recognizers, "analyzer", lambda: analyze)

    class Api:
        def __init__(self) -> None:
            self.tools: list[Any] = []

        def register_tool(self, tool):
            self.tools.append(tool)

    api = Api()
    extension.setup(api)
    tools = {t.name: t for t in api.tools}
    assert list(tools) == ["find_personal_values", "accept_value", "make_copies"]
    path = str(tmp_path / "invoice.pdf")
    found = json.loads(asyncio.run(tools["find_personal_values"].execute("1", {"path": path})).text)
    assert found["pages"][0]["unconfirmed_candidates"][0]["text"] == "Markus Weber"
    args = {"path": path, "page": 1, "text": "Markus Weber", "type": "person", "owner": ""}
    accepted = json.loads(asyncio.run(tools["accept_value"].execute("2", args)).text)
    assert accepted["located"] is True
    made = json.loads(asyncio.run(tools["make_copies"].execute("3", {"path": path, "n": 1})).text)
    assert made["copies"][0]["leak_check_passed"] is True


def test_workspace_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv(extension.OUT_ENV, raising=False)
    monkeypatch.setenv(extension.PRIVATE_ENV, "/tmp/p")
    assert extension.workspace() == pipeline.Workspace(extension.DEFAULT_OUT, "/tmp/p")


# --- the launcher ------------------------------------------------------------------


def test_tau_gets_the_extension_policy_tools_and_llama_cpp():
    args = agent.tau_args(["-p", "copy it"], "bonsai")
    assert args[:4] == ["--extension", str(agent.EXTENSION), "--append-system-prompt", str(agent.POLICY)]
    assert args[4:] == ["--provider", "llama.cpp", "--model", "bonsai", "-p", "copy it"]
    assert agent.EXTENSION.exists() and agent.POLICY.exists()


def test_the_caller_can_choose_provider_and_model():
    assert "--model" not in agent.tau_args([], None)
    chosen = agent.tau_args(["-m", "other"], "bonsai")
    assert "bonsai" not in chosen and chosen[-2:] == ["-m", "other"]
    hosted = agent.tau_args(["--provider", "openai"], "bonsai")
    assert "llama.cpp" not in hosted and "bonsai" not in hosted
    assert agent.has_option(["--model=x"], "--model") and not agent.has_option(["--models"], "--model")


def test_tau_environment_keeps_sessions_private():
    env = agent.tau_env({extension.PRIVATE_ENV: "/p"})
    assert env == {
        "LLAMA_BASE_URL": vl.BASE,
        "TAU_HOME": "/p/tau",
        extension.PRIVATE_ENV: "/p",
        extension.OUT_ENV: extension.DEFAULT_OUT,
    }
    chosen = agent.tau_env({"LLAMA_BASE_URL": "http://x", "TAU_HOME": "/t", extension.OUT_ENV: "/o"})
    assert chosen["LLAMA_BASE_URL"] == "http://x" and chosen["TAU_HOME"] == "/t" and chosen[extension.OUT_ENV] == "/o"


def test_the_launcher_stops_without_a_server(monkeypatch):
    assert agent.server_problem("http://127.0.0.1:9", timeout=1)
    monkeypatch.setattr(agent, "server_problem", lambda base: "connection refused")
    with pytest.raises(SystemExit, match=r"no llama\.cpp server"):
        cli.main(["-p", "hi"])


def test_the_launcher_hands_over_to_tau(monkeypatch, tmp_path):
    started: dict[str, Any] = {}
    monkeypatch.setattr(agent, "server_problem", lambda base: None)
    monkeypatch.setenv(extension.PRIVATE_ENV, str(tmp_path / "private"))
    monkeypatch.delenv("TAU_HOME", raising=False)

    monkeypatch.setattr(tau_coding.cli, "app", lambda args, prog_name: started.update(args=args, prog=prog_name))
    cli.main(["-p", "hi"])
    assert started["prog"] == "presidio-agent" and started["args"][-2:] == ["-p", "hi"]
    assert (tmp_path / "private" / "tau").is_dir()
