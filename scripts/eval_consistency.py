#!/usr/bin/env python3
"""Compare what the model detected on each simulated scan with its digital twin.

    python scripts/eval_consistency.py /dev/shm/presidio-agent/eval.private

Both show the same content, so a value found in one and not the other estimates the
detection recall the leak check cannot see. Reads the private analyses; prints counts
only, never values.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def detected(folder: Path, doc: str) -> set[str]:
    out: set[str] = set()
    for path in sorted(folder.glob(f"{doc}.p*.analysis.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.update(re.sub(r"[^0-9A-ZÄÖÜß]", "", v["text"].upper()) for v in data["values"])
    return out


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/dev/shm/presidio-agent/eval.private")
    docs = sorted({p.name.split(".p")[0] for p in (root / "digital").glob("*.analysis.json")})
    print("| Document | Digital | Scan | Both | Digital only | Scan only |")
    print("| --- | --- | --- | --- | --- | --- |")
    distinct = both = 0
    for doc in docs:
        a, b = detected(root / "digital", doc), detected(root / "sim", doc)
        distinct, both = distinct + len(a | b), both + len(a & b)
        print(f"| {doc} | {len(a)} | {len(b)} | {len(a & b)} | {len(a - b)} | {len(b - a)} |")
    print(f"\nagreement: {both} of {distinct} distinct values found in both versions")


if __name__ == "__main__":
    main()
