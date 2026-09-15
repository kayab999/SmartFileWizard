from __future__ import annotations

"""Informative catalog of known perception models (no download, no network).

Only documentation in code: helps pick `model` / `base_url` in perception.yaml.
Weights are never bundled (see ADR-0003); HTTP endpoints are user-supplied.
"""

VALID_ROLES: tuple[str, ...] = ("ocr", "vision", "zeroshot")

# Stable `id` values are referenced by the CLI and may be used by UIs.
KNOWN_MODELS: list[dict] = [
    {
        "role": "ocr",
        "id": "glm-ocr",
        "default_model": "GLM-OCR-Q8_0",
        "default_base_url": "http://127.0.0.1:8080/v1",
        "notes": "Default OCR (llama-server -hf ggml-org/GLM-OCR-GGUF:Q8_0)",
    },
    {
        "role": "ocr",
        "id": "qwen3-vl-2b",
        "default_model": "Qwen3-VL-2B-Instruct",
        "default_base_url": "http://127.0.0.1:8081/v1",
        "notes": "Small VLM that also reads text well (stage 2 alt)",
    },
    {
        "role": "ocr",
        "id": "qwen2.5-vl-7b",
        "default_model": "Qwen2.5-VL-7B-Instruct",
        "default_base_url": "http://127.0.0.1:8081/v1",
        "notes": "Heavier OCR; better on complex multi-column layouts",
    },
    {
        "role": "vision",
        "id": "qwen3-vl-2b",
        "default_model": "Qwen3-VL-2B-Instruct",
        "default_base_url": "http://127.0.0.1:8081/v1",
        "notes": "Default stage-3 VLM (label classification JSON)",
    },
    {
        "role": "vision",
        "id": "qwen3-vl-4b",
        "default_model": "Qwen3-VL-4B-Instruct",
        "default_base_url": "http://127.0.0.1:8081/v1",
        "notes": "Next-level VLM; needs more VRAM than 2B",
    },
    {
        "role": "vision",
        "id": "qwen2.5-vl-7b",
        "default_model": "Qwen2.5-VL-7B-Instruct",
        "default_base_url": "http://127.0.0.1:8081/v1",
        "notes": "Higher accuracy on fine-grained labels",
    },
    {
        "role": "zeroshot",
        "id": "clip-vit-base-patch32",
        "default_model": "openai/clip-vit-base-patch32",
        "notes": "Default stage-1 model (pip install filewizard[zeroshot])",
    },
    {
        "role": "zeroshot",
        "id": "siglip-base-patch16-224",
        "default_model": "google/siglip-base-patch16-224",
        "notes": "Alternative stage-1; often better embeddings (needs transformers)",
    },
]


def list_known_models(role: str | None = None) -> list[dict]:
    """
    Return catalog entries as copies, optionally filtered by role.

    Unknown role raises ValueError (mirrors config_from_profile).
    """
    if role is not None and role not in VALID_ROLES:
        raise ValueError(
            f"Unknown perception role {role!r}. "
            f"Known: {', '.join(VALID_ROLES)}"
        )
    if role is None:
        return [dict(item) for item in KNOWN_MODELS]
    return [dict(item) for item in KNOWN_MODELS if item["role"] == role]