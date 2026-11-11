"""OCR / vision prompt templates (A3: EN/ES selectable via config).

English is the default: instruction-tuned VLMs generally follow English
instructions more reliably. Spanish templates are provided for models
fine-tuned or prompted in Spanish (``prompt_language: es``).
"""

from __future__ import annotations

_EN_OCR = (
    "Text Recognition: Extract all readable text from this image. "
    "Return only the plain text content, no commentary."
)

_ES_OCR = (
    "Reconocimiento de texto: extrae todo el texto legible de esta imagen. "
    "Devuelve solo el texto plano, sin comentarios."
)

_EN_LABELS_TEMPLATE = (
    "You classify a single image for a file-organization tool.\n"
    "Score each label from 0.0 to 1.0: {labels_csv}.\n"
    'Also extract any visible text into field "text" (string, may be empty).\n'
    "Respond with ONLY a JSON object, no markdown fences, of the form:\n"
    '{"labels": {"screenshot": 0.0, "document": 0.0}, "text": ""}\n'
    'Include every requested label key inside "labels".'
)

_ES_LABELS_TEMPLATE = (
    "Clasificas una sola imagen para una herramienta de organización de "
    "archivos.\n"
    "Puntúa cada etiqueta de 0.0 a 1.0: {labels_csv}.\n"
    "Extrae también cualquier texto visible en el campo \"text\" "
    "(cadena, puede estar vacío).\n"
    "Responde SOLO con un objeto JSON, sin cercas de markdown, con la forma:\n"
    '{"labels": {"screenshot": 0.0, "document": 0.0}, "text": ""}\n'
    'Incluye cada etiqueta solicitada dentro de "labels".'
)


def ocr_user_prompt(*, language: str = "en") -> str:
    """OCR instruction prompt in the configured language."""
    return _ES_OCR if language == "es" else _EN_OCR


def vision_labels_prompt(labels: list[str], *, language: str = "en") -> str:
    """Vision labelling prompt in the configured language."""
    labels_csv = ", ".join(labels)
    template = _ES_LABELS_TEMPLATE if language == "es" else _EN_LABELS_TEMPLATE
    return template.format(labels_csv=labels_csv)
