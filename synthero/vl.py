"""Client for an OpenAI-compatible vision model server (llama-server or a router such as the Llama app)."""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.request

from PIL import Image

BASE = os.environ.get("SYNTHERO_VL", "http://127.0.0.1:18930")
# A router such as the Llama app needs the model name; a single-model server ignores it.
MODEL = os.environ.get("SYNTHERO_MODEL")

Part = dict[str, object]


def image_part(img: Image.Image) -> Part:
    """A chat message part carrying an image."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": url}}


def text_part(text: str) -> Part:
    return {"type": "text", "text": text}


def chat(content: list[Part], max_tokens: int = 4096, timeout: float = 900) -> str:
    body: dict[str, object] = {
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if MODEL:
        body["model"] = MODEL
    req = urllib.request.Request(
        BASE + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        answer = json.load(r)["choices"][0]["message"]["content"]
    if not isinstance(answer, str):
        raise ValueError(f"model answer is not text: {answer!r}")
    return answer


def parse_objects(text: str) -> list[object]:
    """Every complete JSON object in a model answer, also when the array around them was cut off."""
    decoder = json.JSONDecoder()
    out: list[object] = []
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        out.append(obj)
        i = text.find("{", end)
    return out


def read_text(img: Image.Image) -> str:
    """Read the text in a small crop."""
    prompt = "Read the text in this image exactly. Answer with only the text."
    return chat([image_part(img), text_part(prompt)], max_tokens=200).strip()


def read_page(img: Image.Image) -> str:
    """Read a whole page, top to bottom."""
    prompt = "Read all the text on this page, top to bottom, exactly as printed. Answer with only the text."
    return chat([image_part(img), text_part(prompt)], max_tokens=4096)
