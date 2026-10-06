"""Client for an OpenAI-compatible vision model server (llama-server or a router such as the Llama app)."""

from __future__ import annotations

import base64
import functools
import io
import json
import os
import urllib.request

from PIL import Image

BASE_ENV = "PRESIDIO_AGENT_VL"
BASE = os.environ.get(BASE_ENV, "http://127.0.0.1:8080")  # llama-server's default address
MODEL_ENV = "PRESIDIO_AGENT_MODEL"


def served_model(models: object) -> str | None:
    """The model a `/v1/models` answer offers: the only one, or the first loaded one of a router."""
    data = models.get("data") if isinstance(models, dict) else None
    rows = data if isinstance(data, list) else []
    entries = [m for m in rows if isinstance(m, dict) and isinstance(m.get("id"), str)]
    loaded = [m for m in entries if (m.get("status") or {}).get("value", "loaded") == "loaded"]
    chosen = loaded or entries
    return str(chosen[0]["id"]) if chosen else None


@functools.cache
def model() -> str | None:
    """The model to ask for: PRESIDIO_AGENT_MODEL, or else the one the server serves."""
    if name := os.environ.get(MODEL_ENV):
        return name
    try:
        with urllib.request.urlopen(BASE + "/v1/models", timeout=10) as r:
            return served_model(json.loads(r.read()))
    except (OSError, ValueError):
        return None


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
    if name := model():
        body["model"] = name
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


def upscaled(img: Image.Image, min_height: int = 64) -> Image.Image:
    """A small crop enlarged so its text is about as tall as the model reads best."""
    if img.height >= min_height or img.height == 0:
        return img
    scale = min_height / img.height
    return img.resize((round(img.width * scale), min_height), Image.Resampling.LANCZOS)


def read_text(img: Image.Image) -> str:
    """Read the text in a small crop."""
    prompt = "Read the text in this image exactly, character by character. Answer with only the text."
    return chat([image_part(upscaled(img)), text_part(prompt)], max_tokens=200).strip()


def read_page(img: Image.Image) -> str:
    """Read a whole page, top to bottom."""
    prompt = "Read all the text on this page, top to bottom, exactly as printed. Answer with only the text."
    return chat([image_part(img), text_part(prompt)], max_tokens=4096)
