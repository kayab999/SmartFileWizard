from __future__ import annotations

import json
from pathlib import Path
from typing import Any

class AgentFeaturesError(Exception):
    """Raised when an agent-features JSON file cannot be loaded or validated."""


def _norm_key(key: str) -> str:
    """Normalize a mapping key to an absolute resolved path string."""
    return str(Path(key).expanduser().resolve())


def normalize_agent_features(raw: Any) -> dict[str, dict]:
    """Validate + normalize an in-memory agent-features mapping.

    Accepts the same shape `load_agent_features` returns (path -> feature
    dict) and raises `AgentFeaturesError` on invalid input, so the MCP tool
    can reuse one canonical validator without touching the filesystem.
    """
    if not isinstance(raw, dict):
        raise AgentFeaturesError(
            f"Agent features must be an object (path -> feature dict), "
            f"got {type(raw).__name__}"
        )

    mapping: dict[str, dict] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise AgentFeaturesError(
                f"Agent features: entry {key!r} must be a dict, "
                f"got {type(value).__name__}"
            )
        mapping[_norm_key(str(key))] = value
    return mapping


def load_agent_features(path: Path | str) -> dict[str, dict]:
    """
    Load an agent-features JSON mapping: absolute path -> feature dict.

    Feature dicts use the same shape the cascade produces:

        {
          "/abs/path/to/file.jpg": {
            "vision":  {"invoice": 0.91, "document": 0.8, "provider": "agent"},
            "ocr":     {"text": "Factura …", "provider": "agent"},
            "cascade": {"stage_used": 0, "category": "factura",
                        "confidence": 0.91, "status": "confirmed"}
          }
        }

    Relative keys are resolved against the CWD. Invalid JSON or a non-dict
    value raises AgentFeaturesError (never silently skipped).
    """
    path = Path(path).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentFeaturesError(f"Cannot load agent features {path}: {exc}") from exc

    return normalize_agent_features(raw)


class AgentFeaturesExtractor:
    """
    FeatureExtractor that injects precomputed agent evidence.

    Ordering (fixed decision for WP-0.5.3): this extractor runs AFTER the
    cascade extractor, so agent-provided top-level keys override cascade
    evidence (collect_facts does a shallow `features.update` per extractor,
    i.e. last-wins). Place it BEFORE the cascade if you want the opposite.
    """

    name = "agent_inject"

    def __init__(self, mapping: dict[str, dict]):
        self.mapping = mapping

    def extract(self, path: Path) -> dict[str, Any]:
        return self.mapping.get(_norm_key(str(path)), {})
