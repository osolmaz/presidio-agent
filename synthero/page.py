"""Build a static comparison page for synthero outputs.

    python3 -m synthero.page OUT_DIR

Writes OUT_DIR/index.html: for each scan, the original, the located values
(red: by OCR, orange: by pixels), and every copy with its answer key. Relative links only.
"""

from __future__ import annotations

import glob
import html
import json
import os
import sys

from synthero.synth import Change, Key


def figure(src: str, title: str, body: str = "") -> str:
    return (
        f'<figure><a href="{src}" target="_blank"><img src="{src}" loading="lazy" alt=""></a>'
        f"<figcaption><b>{html.escape(title)}</b>{body}</figcaption></figure>"
    )


def key_table(key: Key) -> str:
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


def build(out: str) -> str:
    sections: list[str] = []
    for orig in sorted(glob.glob(os.path.join(out, "*.original.png"))):
        stem = os.path.basename(orig)[: -len(".original.png")]
        cards = [
            figure(f"{stem}.original.png", "Original scan"),
            figure(
                f"{stem}.boxes.png",
                "Found lines",
                "<span>red: OCR, purple: OCR corrected by a second reading, orange: pixels</span>",
            ),
        ]
        for img in sorted(glob.glob(os.path.join(out, f"{stem}.copy-*.png"))):
            with open(img[:-4] + ".json", encoding="utf-8") as f:
                key: Key = json.load(f)
            ok = sum(c["read_back_ok"] for c in key["changes"])
            title = (
                f"{os.path.basename(img)[len(stem) + 1 : -4]}: {ok}/{len(key['changes'])} values replaced and read back"
            )
            cards.append(figure(os.path.basename(img), title, key_table(key)))
        sections.append(f"<section><h2>{html.escape(stem)}</h2><div class=row>{''.join(cards)}</div></section>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>synthero outputs</title><style>
:root {{ --bg:#f6f6f3; --ink:#1d1f22; --muted:#5f6368; --card:#fff; --rule:#ddd;
  --ok:#1d7a3a; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141517; --ink:#e8e8e6; --muted:#a0a3a8; --card:#1e2023;
  --rule:#33363a; --ok:#6fd08c; --bad:#ff8a80; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui, sans-serif;
  padding:24px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:28px 0 10px; }}
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
<p>Each copy changes only the found fields, inside their own boxes; every other pixel is the original scan.
Click an image for full size. Files live in RAM and disappear at reboot.</p>
{"".join(sections)}
</body></html>"""
    path = os.path.join(out, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


if __name__ == "__main__":
    print("wrote", build(sys.argv[1] if len(sys.argv) > 1 else "/dev/shm/synthero/out"))
