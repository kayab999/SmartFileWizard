from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def host_is_loopback(base_url: str) -> bool:
    """True when the URL host is this machine (images stay local)."""
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def remote_perception_endpoints(config) -> list[str]:
    """Non-loopback llama_http endpoints (I9: images would leave the host).

    Duck-typed on config (PerceptionConfig) so CLI/GUI/MCP share one check.
    """
    remote: list[str] = []
    ocr = getattr(config, "ocr", None)
    if (
        getattr(ocr, "provider", None) == "llama_http"
        and not host_is_loopback(str(getattr(ocr, "base_url", "")))
    ):
        remote.append(f"OCR {ocr.base_url}")
    vision = getattr(config, "vision", None)
    if (
        getattr(vision, "provider", None) == "llama_http"
        and not host_is_loopback(str(getattr(vision, "base_url", "")))
    ):
        remote.append(f"visión {vision.base_url}")
    return remote

# H4 (0.9.4): single in-flight HTTP call process-wide. OCR/VLM servers are
# local single-slot endpoints; parallel 120s calls pile up. probe_server
# stays unlocked (fast reachability check only).
_HTTP_LOCK = threading.Lock()


def _resize_image_bytes(path: Path, max_edge: int) -> tuple[bytes, str]:
    """Return PNG/JPEG bytes bounded by max_edge (R11)."""
    try:
        from PIL import Image
    except ImportError:
        data = path.read_bytes()
        suffix = path.suffix.lower().lstrip(".") or "png"
        mime = "image/png" if suffix == "png" else f"image/{suffix}"
        return data, mime

    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        scale = min(1.0, float(max_edge) / float(max(w, h, 1)))
        if scale < 1.0:
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"


def chat_completion_with_image(
    *,
    base_url: str,
    model: str,
    prompt: str,
    image_path: Path,
    timeout_s: float = 120.0,
    max_image_edge: int = 1600,
    temperature: float = 0.0,
) -> str:
    """
    OpenAI-compatible multimodal chat completion.

    POST {base_url}/chat/completions with image as data URL.
    """
    base = base_url.rstrip("/")
    url = f"{base}/chat/completions"

    raw, mime = _resize_image_bytes(image_path, max_image_edge)
    b64 = base64.b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    wait = max(1.0, float(timeout_s) + 5.0)
    acquired = _HTTP_LOCK.acquire(timeout=wait)
    if not acquired:
        raise RuntimeError(
            "OCR/vision HTTP slot busy (timed out waiting for in-flight call)"
        )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach OCR/vision server at {url}: {exc}") from exc
    finally:
        _HTTP_LOCK.release()

    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected response shape: {data!r}") from exc


def probe_server(base_url: str, timeout_s: float = 3.0) -> dict[str, Any]:
    """
    Lightweight reachability check (models list or root).

    HTTP 405 Method Not Allowed still means the port is serving something.
    """
    base = base_url.rstrip("/")
    candidates = [f"{base}/models", base]
    last_error = "unreachable"
    for url in candidates:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return {
                    "ok": True,
                    "url": url,
                    "status": resp.status,
                }
        except urllib.error.HTTPError as exc:
            # Server is up but method/path may differ (e.g. 404/405).
            if exc.code in {404, 405, 401, 403}:
                return {
                    "ok": True,
                    "url": url,
                    "status": exc.code,
                    "note": "reachable (non-GET or auth)",
                }
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "url": base, "error": last_error}


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def parse_vision_json(content: str, labels: list[str]) -> dict[str, Any]:
    """
    Parse model output into vision scores + optional text.

    Tolerates markdown fences and extra prose.
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    match = _JSON_RE.search(text)
    if not match:
        return {
            "labels": {lab: 0.0 for lab in labels},
            "text": "",
            "raw": content,
            "error": "no JSON object in model response",
        }

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {
            "labels": {lab: 0.0 for lab in labels},
            "text": "",
            "raw": content,
            "error": f"invalid JSON: {exc}",
        }

    raw_labels = data.get("labels") if isinstance(data, dict) else None
    if not isinstance(raw_labels, dict):
        # Flat form: {"screenshot": 0.9, ...}
        raw_labels = {
            k: v
            for k, v in (data.items() if isinstance(data, dict) else [])
            if k != "text"
        }

    scores: dict[str, float] = {}
    for lab in labels:
        try:
            scores[lab] = float(raw_labels.get(lab, 0.0))
        except (TypeError, ValueError):
            scores[lab] = 0.0
        scores[lab] = max(0.0, min(1.0, scores[lab]))

    ocr_text = ""
    if isinstance(data, dict) and data.get("text") is not None:
        ocr_text = str(data.get("text") or "")

    result: dict[str, Any] = {"labels": scores, "text": ocr_text}
    if isinstance(data, dict) and data.get("error"):
        result["error"] = str(data["error"])
    return result
