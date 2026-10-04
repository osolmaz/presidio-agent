"""Build a static comparison page for synthero outputs.

    python3 -m synthero.page OUT_DIR

Writes OUT_DIR/index.html: for each document page, the original, the located values,
and every copy with its answer key; one row per page. Relative links only.
"""

from __future__ import annotations

import glob
import html
import json
import os
import sys

from synthero.synth import Change, Key, PageKey


def figure(src: str, title: str, body: str = "") -> str:
    return (
        f'<figure><a href="{src}" target="_blank"><img src="{src}" loading="lazy" alt=""></a>'
        f"<figcaption><b>{html.escape(title)}</b>{body}</figcaption></figure>"
    )


def key_table(key: PageKey) -> str:
    """New values only: the original data never appears on the page."""

    def status(c: Change) -> str:
        if not c["located"]:
            return "<td class=bad>not located</td>"
        return "<td class=ok>yes</td>" if c["read_back_ok"] else "<td class=bad>no</td>"

    rows = "".join(
        f"<tr><td>{html.escape(c['type'])} ({html.escape(c['owner'])})</td>"
        f"<td>{html.escape(c['new'])}</td>{status(c)}</tr>"
        for c in key["changes"]
    )
    lc = key.get("leak_check")
    verdict = ""
    if lc is not None:
        verdict = (
            "<p class=ok>Leak check passed: no original value found on the page.</p>"
            if lc["passed"]
            else f"<p class=bad>Leak check failed for: {html.escape(', '.join(lc['leaked_types']))}</p>"
        )
    return verdict + f"<table><tr><th>value (owner)</th><th>new value</th><th>read back</th></tr>{rows}</table>"


def _load(path: str) -> Key:
    with open(path, encoding="utf-8") as f:
        key: Key = json.load(f)
    return key


def page_row(out: str, stem: str, n: int) -> str:
    cards = [
        figure(f"{stem}.p{n}.original.png", "Original"),
        figure(
            f"{stem}.p{n}.boxes.png",
            "Located values",
            "<span>red: OCR, purple: OCR corrected by a second reading, orange: pixels</span>",
        ),
    ]
    for path in sorted(glob.glob(os.path.join(out, f"{stem}.copy-*.json"))):
        copy = os.path.basename(path)[len(stem) + 1 : -len(".json")]
        page = next((p for p in _load(path)["pages"] if p["page"] == n), None)
        if page is None:
            continue
        ok = sum(c["read_back_ok"] for c in page["changes"])
        title = f"{copy}: {ok}/{len(page['changes'])} values replaced and read back"
        if page["barcodes_scrambled"]:
            title += f", {page['barcodes_scrambled']} barcodes scrambled"
        cards.append(figure(f"{stem}.{copy}.p{n}.png", title, key_table(page)))
    return f"<h3>page {n}</h3><div class=row>{''.join(cards)}</div>"


def build(out: str) -> str:
    sections: list[str] = []
    stems = sorted(
        os.path.basename(p).removesuffix(".p1.original.png") for p in glob.glob(os.path.join(out, "*.p1.original.png"))
    )
    for stem in stems:
        pages = len(glob.glob(os.path.join(out, f"{stem}.p*.original.png")))
        pdfs = "".join(
            f' <a href="{os.path.basename(p)}">{html.escape(os.path.basename(p))}</a>'
            for p in sorted(glob.glob(os.path.join(out, f"{stem}.copy-*.pdf")))
        )
        rows = "".join(page_row(out, stem, n) for n in range(1, pages + 1))
        sections.append(f"<section><h2>{html.escape(stem)}</h2><p>PDF:{pdfs}</p>{rows}</section>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>synthero outputs</title><style>
:root {{ --bg:#f6f6f3; --ink:#1d1f22; --muted:#5f6368; --card:#fff; --rule:#ddd;
  --ok:#1d7a3a; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141517; --ink:#e8e8e6; --muted:#a0a3a8; --card:#1e2023;
  --rule:#33363a; --ok:#6fd08c; --bad:#ff8a80; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui, sans-serif;
  padding:24px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:28px 0 6px; }}
h3 {{ font-size:14px; margin:14px 0 6px; color:var(--muted); }}
p {{ color:var(--muted); margin:0; max-width:75ch; }}
.row {{ display:flex; gap:14px; overflow-x:auto; padding-bottom:8px; align-items:flex-start; }}
figure {{ margin:0; flex:0 0 340px; background:var(--card); border:1px solid var(--rule);
  border-radius:6px; overflow:hidden; }}
figure img {{ display:block; width:100%; height:auto; background:#fff; }}
figcaption {{ padding:8px 10px 10px; display:flex; flex-direction:column; gap:6px; }}
figcaption span {{ color:var(--muted); font-size:12px; }}
table {{ border-collapse:collapse; font-size:11.5px; width:100%; }}
td, th {{ border-top:1px solid var(--rule); padding:3px 4px; text-align:left; vertical-align:top;
  word-break:break-all; }}
.ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }}
</style></head><body>
<h1>synthero outputs</h1>
<p>Each copy changes only the personal values, inside their own boxes; every other pixel is the original.
Click an image for full size. Files live in RAM and disappear at reboot.</p>
{"".join(sections)}
</body></html>"""
    path = os.path.join(out, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


if __name__ == "__main__":
    print("wrote", build(sys.argv[1] if len(sys.argv) > 1 else "/dev/shm/synthero/out"))
