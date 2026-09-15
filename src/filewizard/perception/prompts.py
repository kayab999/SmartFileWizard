from __future__ import annotations


def ocr_user_prompt() -> str:
    return (
        "Text Recognition: Extract all readable text from this image. "
        "Return only the plain text content, no commentary."
    )


def vision_labels_prompt(labels: list[str]) -> str:
    labels_csv = ", ".join(labels)
    return (
        "You classify a single image for a file-organization tool.\n"
        f"Score each label from 0.0 to 1.0: {labels_csv}.\n"
        "Also extract any visible text into field \"text\" (string, may be empty).\n"
        "Respond with ONLY a JSON object, no markdown fences, of the form:\n"
        '{"labels": {"screenshot": 0.0, "document": 0.0}, "text": ""}\n'
        "Include every requested label key inside \"labels\"."
    )
