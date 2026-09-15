from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Intent:
    id: str
    title: str
    description: str
    condition: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    # When set, wizard uses a multi-rule YAML cascade (RuleSet) instead of
    # building a single rule from the conditions/action pages.
    rules_file: str | None = None
    # Named preset in ~/.local/share/filewizard/presets/ (preferred over rules_file).
    preset_name: str | None = None


INTENTS = [
    Intent(
        id="organize",
        title="Organizar archivos",
        description=(
            "Mover archivos a carpetas usando extensión, nombre, tamaño o fecha."
        ),
        condition={},
        action={
            "move_to": "~/Organized/{year}/{month}",
            "rename": "{original_name}",
        },
    ),
    Intent(
        id="rename",
        title="Renombrar archivos",
        description=(
            "Renombrar archivos usando plantillas como fecha o nombre original."
        ),
        condition={},
        action={
            "rename": "{date}_{original_name}",
        },
    ),
    Intent(
        id="images_cascade",
        title="Organizar imágenes (cascada)",
        description=(
            "Cascada afilada multi-regla: capturas, cámara, social, escaneos, "
            "fotos y cubo Misc (preset images-cascade / rules_sharp.yaml)."
        ),
        rules_file="rules_sharp.yaml",
        preset_name="images-cascade",
    ),
    Intent(
        id="images_cascade_ml",
        title="Organizar imágenes (cascada + percepción)",
        description=(
            "Preset images-cascade-ml: reglas por categoría de cascada "
            "(factura, escaneo, foto…). Usa heurísticas y, si está en Ajustes, OCR/VLM."
        ),
        preset_name="images-cascade-ml",
    ),
    Intent(
        id="images",
        title="Organizar imágenes (simple)",
        description="Una sola regla: todas las imágenes por fecha (mtime/heurística).",
        condition={
            "image_only": True,
        },
        action={
            "move_to": "~/Pictures/{year}/{month}",
        },
    ),
    Intent(
        id="screenshots",
        title="Separar capturas",
        description="Detectar capturas de pantalla por nombre y tipo de archivo.",
        condition={
            "image_only": True,
            "filename_regex": "(?i)(screenshot|captura)",
        },
        action={
            "move_to": "~/Pictures/Screenshots/{year}/{month}",
            "rename": "{date}_{original_name}",
        },
    ),
    Intent(
        id="invoices",
        title="Clasificar facturas",
        description="Usar OCR opcional para detectar facturas o recibos.",
        condition={
            "image_only": True,
            "ocr_contains_any": ["factura", "invoice", "subtotal"],
            "enable_ocr": True,
        },
        action={
            "move_to": "~/Documents/Invoices/{year}",
        },
    ),
    Intent(
        id="downloads_docs",
        title="Organizar descargas (docs y media)",
        description=(
            "Preset downloads-docs: PDF, oficina, comprimidos, vídeo y audio. "
            "Las imágenes no se mueven (usa un intent de cascada)."
        ),
        preset_name="downloads-docs",
    ),
    Intent(
        id="automation",
        title="Crear automatización",
        description="Construir una regla personalizada para automatizar una carpeta.",
        condition={},
        action={
            "move_to": "~/Automated/{year}/{month}",
        },
    ),
]
