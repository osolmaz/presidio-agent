"""Build a static comparison page for fake-scan outputs.

    python3 -m fakescan.page OUT_DIR

Writes OUT_DIR/index.html: for each scan, the original, the found lines (red:
changed, blue: kept), and every copy with its answer key. Relative links only.
"""
import glob
import html
import json
import os
import sys


def figure(src, title, body=""):
    return (f'<figure><a href="{src}" target="_blank"><img src="{src}" loading="lazy" alt=""></a>'
            f'<figcaption><b>{html.escape(title)}</b>{body}</figcaption></figure>')


def key_table(key):
    """New values only: the original data never appears on the page."""
    rows = "".join(
        f"<tr><td>{html.escape(', '.join(sorted({sp['type'] + ' (' + sp['owner'] + ')' for sp in c['spans']})))}</td>"
        f"<td>{html.escape(c['new'])}</td>"
        f"<td class={'ok' if c.get('read_back_ok') else 'bad'}>{'yes' if c.get('read_back_ok') else 'no'}</td></tr>"
        for c in key["changes"])
    lc = key.get("leak_check")
    verdict = ""
    if lc is not None:
        verdict = ('<p class=ok>Leak check passed: no original value found on the page.</p>' if lc["passed"] else
                   f'<p class=bad>Leak check failed for: {html.escape(", ".join(lc["leaked_types"]))}</p>')
    return verdict + f'<table><tr><th>PII (owner)</th><th>new line</th><th>read back</th></tr>{rows}</table>'


def build(out):
    sections = []
    for orig in sorted(glob.glob(os.path.join(out, "*.original.png"))):
        stem = os.path.basename(orig)[: -len(".original.png")]
        cards = [figure(f"{stem}.original.png", "Original scan"),
                 figure(f"{stem}.boxes.png", "Found lines", "<span>red: changed, blue: kept</span>")]
        for img in sorted(glob.glob(os.path.join(out, f"{stem}.copy-*.png"))):
            if img.endswith(".private.png"):
                continue
            key = json.load(open(img[:-4] + ".json"))
            ok = sum(c.get("read_back_ok", False) for c in key["changes"])
            title = f"{os.path.basename(img)[len(stem) + 1:-4]}: {ok}/{len(key['changes'])} read back"
            cards.append(figure(os.path.basename(img), title, key_table(key)))
        sections.append(f"<section><h2>{html.escape(stem)}</h2><div class=row>{''.join(cards)}</div></section>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>fake-scan outputs</title><style>
:root {{ --bg:#f6f6f3; --ink:#1d1f22; --muted:#5f6368; --card:#fff; --rule:#ddd; --ok:#1d7a3a; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141517; --ink:#e8e8e6; --muted:#a0a3a8; --card:#1e2023; --rule:#33363a; --ok:#6fd08c; --bad:#ff8a80; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui, sans-serif; padding:24px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:28px 0 10px; }}
p {{ color:var(--muted); margin:0; max-width:75ch; }}
.row {{ display:flex; gap:14px; overflow-x:auto; padding-bottom:8px; align-items:flex-start; }}
figure {{ margin:0; flex:0 0 340px; background:var(--card); border:1px solid var(--rule); border-radius:6px; overflow:hidden; }}
figure img {{ display:block; width:100%; height:auto; background:#fff; }}
figcaption {{ padding:8px 10px 10px; display:flex; flex-direction:column; gap:6px; }}
figcaption span {{ color:var(--muted); font-size:12px; }}
table {{ border-collapse:collapse; font-size:11.5px; width:100%; }}
td, th {{ border-top:1px solid var(--rule); padding:3px 4px; text-align:left; vertical-align:top; word-break:break-all; }}
.ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }}
</style></head><body>
<h1>fake-scan outputs</h1>
<p>Each copy changes only the found fields, inside their own boxes; every other pixel is the original scan.
Click an image for full size. Files live in RAM on isengard and disappear at reboot.</p>
{''.join(sections)}
</body></html>"""
    open(os.path.join(out, "index.html"), "w").write(page)
    return os.path.join(out, "index.html")


if __name__ == "__main__":
    print("wrote", build(sys.argv[1] if len(sys.argv) > 1 else "/dev/shm/fake-scan/out"))
