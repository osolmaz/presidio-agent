"""Client for a local Qwen3-VL llama-server: find text lines and read text back."""
import base64
import io
import json
import os
import re
import urllib.request

from PIL import Image

BASE = os.environ.get("SYNTHERO_VL", "http://127.0.0.1:18930")
# A router such as the Llama app needs the model name; a single-model server ignores it.
MODEL = os.environ.get("SYNTHERO_MODEL")


def _data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def chat(content, max_tokens=4096, timeout=900) -> str:
    body = {"messages": [{"role": "user", "content": content}], "temperature": 0, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False}}
    if MODEL:
        body["model"] = MODEL
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def parse_json(text: str):
    """Take the first JSON array or object out of a model answer."""
    text = re.sub(r"```(?:json)?", "", text)
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON in model answer: " + text[:200])


def locate_lines(img: Image.Image):
    """Return [{"text": str, "box": (x1, y1, x2, y2)}] in pixels."""
    prompt = ("Find every line of text in this scanned document, top to bottom. Answer with only a JSON array. "
              'Each item: {"text": "<the exact text of the line>", "bbox_2d": [x1, y1, x2, y2]}.')
    items = parse_json(chat([{"type": "image_url", "image_url": {"url": _data_url(img)}},
                             {"type": "text", "text": prompt}]))
    coords = [v for it in items for v in it.get("bbox_2d", [])]
    # Qwen3-VL answers in a 0..1000 grid; older Qwen-VL versions answer in pixels.
    relative = bool(coords) and max(coords) <= 1000 and max(img.size) > 1000
    sx, sy = (img.width / 1000, img.height / 1000) if relative else (1, 1)
    lines = []
    for it in items:
        b = it.get("bbox_2d")
        if not b or len(b) != 4 or not str(it.get("text", "")).strip():
            continue
        x1, y1, x2, y2 = b
        lines.append({"text": str(it["text"]).strip(),
                      "box": (round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy))})
    return lines


def read_text(img: Image.Image) -> str:
    """Read the text in a small crop."""
    return chat([{"type": "image_url", "image_url": {"url": _data_url(img)}},
                 {"type": "text", "text": "Read the text in this image exactly. Answer with only the text."}],
                max_tokens=200).strip()
