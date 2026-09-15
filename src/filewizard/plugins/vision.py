from __future__ import annotations

from pathlib import Path
from typing import Any


class StubVision:
    """
    Placeholder vision provider.

    A real provider should return:

      {
        "vision": {
          "document": 0.94,
          "screenshot": 0.02,
          "photo": 0.87,
        }
      }

    Production guidance:
      - do not ship the model inside the main binary
      - allow local backends: ONNX, OpenVINO, Ollama
      - allow optional remote APIs
    """

    name = "vision"

    def extract(self, path: Path) -> dict[str, Any]:
        return {
            "vision": {}
        }
