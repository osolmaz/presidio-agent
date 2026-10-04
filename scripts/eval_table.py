#!/usr/bin/env python3
"""Summarise an eval folder (scripts/eval.sh) as a Markdown table, from the public keys only.

python scripts/eval_table.py /dev/shm/synthero/eval
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def row(set_name: str, key_path: Path) -> str:
    key = json.loads(key_path.read_text(encoding="utf-8"))
    pages = key["pages"]
    changes = [c for p in pages for c in p["changes"]]
    located = sum(c["located"] for c in changes)
    edited = [c for c in changes if c["places"]]
    read_back = sum(c["read_back_ok"] for c in edited)
    bars = sum(p["barcodes_scrambled"] for p in pages)
    leaked = sorted({t for p in pages for t in p.get("leak_check", {}).get("leaked_types", [])})
    verdict = "passed" if not leaked else "failed: " + ", ".join(leaked)
    doc = key_path.name.split(".copy-")[0]
    return (
        f"| {set_name} | {doc} | {len(pages)} | {len(changes)} | {located} | {len(edited)} | "
        f"{read_back} | {bars} | {verdict} |"
    )


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/dev/shm/synthero/eval")
    print("| Set | Document | Pages | Values | Located | Edited | Read back | Barcodes scrambled | Leak check |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for set_name in ("real", "sim", "digital"):
        for key_path in sorted((root / set_name).glob("*.copy-1.json")):
            print(row(set_name, key_path))


if __name__ == "__main__":
    main()
