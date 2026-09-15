from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .intents import Intent
from .options import csv_from_value
from .preview_dialog import PreviewDialog
from .theme import ALERT, MUTED, SUCCESS
from .util import STATUS_GLYPHS, elide_middle, safe_display
from .workers import ExecuteWorker, PreviewWorker

_WIZARD_STEPS = ("1. Archivos", "2. Condiciones", "3. Acción", "4. Revisar")

_OP_INDEX_ROLE = Qt.ItemDataRole.UserRole
_PLACEHOLDER_ROLE = Qt.ItemDataRole.UserRole + 1


class SourcePage(QWidget):
    def __init__(self, intent: Intent, parent=None):
        super().__init__(parent)

        self.intent = intent

        layout = QVBoxLayout(self)

        title = QLabel("Archivos")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title.setFont(title_font)

        description = QLabel(
            "Selecciona la carpeta donde FileWizard buscará archivos."
        )
        description.setWordWrap(True)

        form = QGridLayout()

        self.source_edit = QLineEdit()
        self.source_edit.setAccessibleName("Carpeta origen")
        default_source = Path.home() / "Downloads"
        if not default_source.exists():
            default_source = Path.home()
        self.source_edit.setText(str(default_source))

        browse_button = QPushButton("Examinar...")
        browse_button.clicked.connect(self.choose_source)

        self.include_hidden = QCheckBox("Incluir archivos ocultos")
        self.include_hidden.setChecked(False)

        self.enable_ocr = QCheckBox(
            "Forzar OCR (etapa 2; si la cascada está ON en Ajustes ya puede usarlo)"
        )
        self.enable_ocr.setChecked(bool(intent.condition.get("enable_ocr", False)))

        self.enable_vision = QCheckBox(
            "Forzar VLM (etapa 3; la cascada en Ajustes decide si hace falta)"
        )
        self.enable_vision.setChecked(
            bool(intent.condition.get("enable_vision", False))
        )

        self.limit = QSpinBox()
        self.limit.setMinimum(0)
        self.limit.setMaximum(1_000_000)
        self.limit.setValue(100)
        self.limit.setSuffix(" archivos")
        self.limit.setSpecialValueText("Todos")

        form.addWidget(QLabel("Carpeta origen"), 0, 0)
        form.addWidget(self.source_edit, 0, 1)
        form.addWidget(browse_button, 0, 2)

        form.addWidget(self.include_hidden, 1, 1, 1, 2)
        form.addWidget(self.enable_ocr, 2, 1, 1, 2)
        form.addWidget(self.enable_vision, 3, 1, 1, 2)

        form.addWidget(QLabel("Límite de escaneo"), 4, 0)
        form.addWidget(self.limit, 4, 1, 1, 2)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(10)
        layout.addLayout(form)
        layout.addStretch()

    def choose_source(self) -> None:
        current = self.source_edit.text().strip() or str(Path.home())

        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta origen",
            current,
        )

        if directory:
            self.source_edit.setText(directory)

    def options(self) -> dict[str, Any]:
        return {
            "source": self.source_edit.text().strip(),
            "include_hidden": self.include_hidden.isChecked(),
            "enable_ocr": self.enable_ocr.isChecked(),
            "enable_vision": self.enable_vision.isChecked(),
            "limit": self.limit.value(),
        }

    def validate(self) -> bool:
        source_text = self.source_edit.text().strip()

        if not source_text:
            QMessageBox.critical(
                self,
                "FileWizard",
                "Selecciona una carpeta origen.",
            )
            return False

        source = Path(source_text).expanduser()

        if not source.exists() or not source.is_dir():
            QMessageBox.critical(
                self,
                "FileWizard",
                f"La carpeta origen no existe o no es un directorio:\n\n{source}",
            )
            return False

        return True


class ConditionsPage(QWidget):
    def __init__(self, intent: Intent, parent=None):
        super().__init__(parent)

        self.intent = intent

        layout = QVBoxLayout(self)

        title = QLabel("Condiciones")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title.setFont(title_font)

        description = QLabel(
            "Define cuándo un archivo debe coincidir. "
            "Si no defines condiciones, puedes marcar 'Todos los archivos'."
        )
        description.setWordWrap(True)

        form = QGridLayout()

        self.always = QCheckBox("Todos los archivos (sin condiciones)")
        self.always.setChecked(bool(intent.condition.get("always", False)))

        self.extensions = QLineEdit(
            csv_from_value(intent.condition.get("extensions"))
        )
        self.extensions.setPlaceholderText("jpg, png, pdf, txt")

        self.filename_regex = QLineEdit(
            str(intent.condition.get("filename_regex") or "")
        )
        self.filename_regex.setPlaceholderText("(?i)screenshot|captura")

        self.path_contains = QLineEdit(
            csv_from_value(intent.condition.get("path_contains"))
        )
        self.path_contains.setPlaceholderText("Downloads, temporal")

        self.ocr_contains_any = QLineEdit(
            csv_from_value(intent.condition.get("ocr_contains_any"))
        )
        self.ocr_contains_any.setPlaceholderText("factura, invoice, subtotal")

        self.filename_pattern_any = QLineEdit(
            csv_from_value(intent.condition.get("filename_pattern_any"))
        )
        self.filename_pattern_any.setPlaceholderText("whatsapp, screenshot, invoice")

        self.not_filename_pattern_any = QLineEdit(
            csv_from_value(intent.condition.get("not_filename_pattern_any"))
        )
        self.not_filename_pattern_any.setPlaceholderText("whatsapp (excluir)")

        self.cascade_category_any = QLineEdit(
            csv_from_value(intent.condition.get("cascade_category_any"))
        )
        self.cascade_category_any.setPlaceholderText("factura, recibo (necesita cascada)")

        self.has_camera_metadata = QComboBox()
        self.has_camera_metadata.addItem("Indiferente", None)
        self.has_camera_metadata.addItem("Con EXIF de cámara", True)
        self.has_camera_metadata.addItem("Sin EXIF de cámara", False)
        _cam = intent.condition.get("has_camera_metadata")
        self.has_camera_metadata.setCurrentIndex(
            1 if _cam is True else (2 if _cam is False else 0)
        )

        self.size_gt_mb = QSpinBox()
        self.size_gt_mb.setMinimum(0)
        self.size_gt_mb.setMaximum(1_000_000)
        self.size_gt_mb.setSuffix(" MB")
        self.size_gt_mb.setValue(int(intent.condition.get("size_gt_mb", 0) or 0))

        self.older_than_days = QSpinBox()
        self.older_than_days.setMinimum(0)
        self.older_than_days.setMaximum(36500)
        self.older_than_days.setSuffix(" días")
        self.older_than_days.setSpecialValueText("Sin límite")
        self.older_than_days.setValue(
            int(intent.condition.get("older_than_days", 0) or 0)
        )

        self.image_only = QCheckBox("Solo imágenes")
        self.image_only.setChecked(bool(intent.condition.get("image_only", False)))

        form.addWidget(self.always, 0, 0, 1, 2)

        form.addWidget(QLabel("Extensiones"), 1, 0)
        form.addWidget(self.extensions, 1, 1)

        form.addWidget(QLabel("Regex nombre"), 2, 0)
        form.addWidget(self.filename_regex, 2, 1)

        form.addWidget(QLabel("Ruta contiene"), 3, 0)
        form.addWidget(self.path_contains, 3, 1)

        form.addWidget(QLabel("OCR contiene"), 4, 0)
        form.addWidget(self.ocr_contains_any, 4, 1)

        form.addWidget(QLabel("Patrón nombre"), 5, 0)
        form.addWidget(self.filename_pattern_any, 5, 1)

        form.addWidget(QLabel("Excluir patrón"), 6, 0)
        form.addWidget(self.not_filename_pattern_any, 6, 1)

        form.addWidget(QLabel("Categoría cascada"), 7, 0)
        form.addWidget(self.cascade_category_any, 7, 1)

        form.addWidget(QLabel("EXIF cámara"), 8, 0)
        form.addWidget(self.has_camera_metadata, 8, 1)

        form.addWidget(QLabel("Tamaño mayor que"), 9, 0)
        form.addWidget(self.size_gt_mb, 9, 1)

        form.addWidget(QLabel("Más antiguo que"), 10, 0)
        form.addWidget(self.older_than_days, 10, 1)

        form.addWidget(self.image_only, 11, 1)

        # Fase 3 (SR): associate labels with fields for screen readers.
        for _row in range(1, 11):
            _label = form.itemAtPosition(_row, 0)
            _field = form.itemAtPosition(_row, 1)
            if _label is None or _field is None:
                continue
            _lw, _fw = _label.widget(), _field.widget()
            if isinstance(_lw, QLabel) and isinstance(
                _fw, (QLineEdit, QComboBox, QSpinBox)
            ):
                _lw.setBuddy(_fw)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(10)
        layout.addLayout(form)
        layout.addStretch()

    def options(self) -> dict[str, Any]:
        return {
            "always": self.always.isChecked(),
            "extensions": self.extensions.text().strip(),
            "filename_regex": self.filename_regex.text().strip(),
            "path_contains": self.path_contains.text().strip(),
            "ocr_contains_any": self.ocr_contains_any.text().strip(),
            "filename_pattern_any": self.filename_pattern_any.text().strip(),
            "not_filename_pattern_any": self.not_filename_pattern_any.text().strip(),
            "cascade_category_any": self.cascade_category_any.text().strip(),
            "has_camera_metadata": self.has_camera_metadata.currentData(),
            "size_gt_mb": self.size_gt_mb.value(),
            "older_than_days": self.older_than_days.value() or None,
            "image_only": self.image_only.isChecked(),
        }

    def validate(self) -> bool:
        if self.always.isChecked():
            return True

        extensions = self.extensions.text().strip()
        filename_regex = self.filename_regex.text().strip()
        path_contains = self.path_contains.text().strip()
        ocr_contains_any = self.ocr_contains_any.text().strip()
        filename_pattern_any = self.filename_pattern_any.text().strip()
        not_filename_pattern_any = self.not_filename_pattern_any.text().strip()
        cascade_category_any = self.cascade_category_any.text().strip()
        has_camera_metadata = self.has_camera_metadata.currentData()
        size_gt_mb = self.size_gt_mb.value()
        image_only = self.image_only.isChecked()

        has_condition = any(
            [
                extensions,
                filename_regex,
                path_contains,
                ocr_contains_any,
                filename_pattern_any,
                not_filename_pattern_any,
                cascade_category_any,
                has_camera_metadata is not None,
                size_gt_mb > 0,
                image_only,
            ]
        )

        if not has_condition:
            QMessageBox.critical(
                self,
                "FileWizard",
                "Define al menos una condición o marca 'Todos los archivos'.",
            )
            return False

        if filename_regex:
            try:
                re.compile(filename_regex)
            except re.error as exc:
                QMessageBox.critical(
                    self,
                    "FileWizard",
                    f"La expresión regular no es válida:\n\n{exc}",
                )
                return False

        return True


class ActionPage(QWidget):
    def __init__(self, intent: Intent, parent=None):
        super().__init__(parent)

        self.intent = intent

        layout = QVBoxLayout(self)

        title = QLabel("Acción")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title.setFont(title_font)

        description = QLabel(
            "Define qué hacer con los archivos coincidentes. "
            "Puedes mover, renombrar o ambas cosas."
        )
        description.setWordWrap(True)

        form = QGridLayout()

        self.move_to = QLineEdit(str(intent.action.get("move_to") or ""))
        self.move_to.setPlaceholderText("~/Documents/Invoices/{year}/{month}")

        browse_button = QPushButton("Examinar...")
        browse_button.clicked.connect(self.choose_destination)

        self.rename = QLineEdit(str(intent.action.get("rename") or ""))
        self.rename.setPlaceholderText("{date}_{original_name}")

        self.create_target_dir = QCheckBox("Crear carpeta destino si no existe")
        self.create_target_dir.setChecked(
            bool(intent.action.get("create_target_dir", True))
        )

        self.on_collision = QComboBox()
        self.on_collision.addItems(["append", "skip", "replace"])

        collision = str(intent.action.get("on_collision", "append"))
        collision_index = self.on_collision.findText(collision)
        if collision_index >= 0:
            self.on_collision.setCurrentIndex(collision_index)

        move_label = QLabel("Mover a")
        move_label.setBuddy(self.move_to)
        form.addWidget(move_label, 0, 0)
        form.addWidget(self.move_to, 0, 1)
        form.addWidget(browse_button, 0, 2)

        rename_label = QLabel("Renombrar como")
        rename_label.setBuddy(self.rename)
        form.addWidget(rename_label, 1, 0)
        form.addWidget(self.rename, 1, 1, 1, 2)

        form.addWidget(self.create_target_dir, 2, 1, 1, 2)

        collision_label = QLabel("Colisión")
        collision_label.setBuddy(self.on_collision)
        form.addWidget(collision_label, 3, 0)
        form.addWidget(self.on_collision, 3, 1, 1, 2)

        help_label = QLabel(
            "Plantillas disponibles:\n"
            "{original_name}, {stem}, {ext}, {year}, {month}, {day}, "
            "{date}, {datetime}, {cascade_category}"
        )
        help_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(10)
        layout.addLayout(form)
        layout.addSpacing(10)
        layout.addWidget(help_label)
        layout.addStretch()

    def choose_destination(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta destino",
            str(Path.home()),
        )

        if directory:
            self.move_to.setText(directory)

    def options(self) -> dict[str, Any]:
        return {
            "move_to": self.move_to.text().strip(),
            "rename": self.rename.text().strip(),
            "create_target_dir": self.create_target_dir.isChecked(),
            "on_collision": self.on_collision.currentText(),
        }

    def validate(self) -> bool:
        move_to = self.move_to.text().strip()
        rename = self.rename.text().strip()

        if not move_to and not rename:
            QMessageBox.critical(
                self,
                "FileWizard",
                "La acción debe incluir al menos 'Mover a' o 'Renombrar como'.",
            )
            return False

        if move_to:
            expanded = Path(move_to).expanduser()

            if not expanded.is_absolute():
                QMessageBox.critical(
                    self,
                    "FileWizard",
                    "La ruta de destino debe ser absoluta o comenzar con ~.\n\n"
                    "Ejemplo:\n~/Documents/Invoices/{year}",
                )
                return False

        if rename:
            if "/" in rename or "\x00" in rename:
                QMessageBox.critical(
                    self,
                    "FileWizard",
                    "El nombre de archivo no puede contener '/'.",
                )
                return False

        return True


class ReviewPage(QWidget):
    """
    V0.3.2 — preview grouped by destination folder.

    Top-level rows = destination directories (counts).
    Children = files (lazy-filled; expand to inspect / override).
    """

    MAX_CHILDREN_PER_GROUP = 2000
    open_preview = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._operations: list[Any] = []
        self._groups: dict[str, list[int]] = {}

        layout = QVBoxLayout(self)

        title = QLabel("Revisar")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title.setFont(title_font)

        self.summary = QLabel("Todavía no hay vista previa.")
        self.summary.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            ["Destino / archivo", "Regla", "Estado", "Motivo"]
        )
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 140)
        self.tree.setColumnWidth(2, 90)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemExpanded.connect(self._populate_group_children)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        # Keyboard Enter activates the focused item just like double-click.
        self.tree.itemActivated.connect(self._on_item_double_clicked)

        hint = QLabel(
            "Agrupado por carpeta destino. Expande un grupo para ver archivos. "
            "Doble clic en un archivo → vista previa / Mover a…"
        )
        hint.setWordWrap(True)

        self.open_folder_after = QCheckBox(
            "Abrir carpeta destino al terminar"
        )
        self.open_folder_after.setChecked(False)

        save_row = QHBoxLayout()
        self.save_preset_name = QLineEdit()
        self.save_preset_name.setPlaceholderText("nombre-del-preset")
        self.save_preset_btn = QPushButton("Guardar como preset")
        self.save_preset_btn.setToolTip(
            "Guarda el RuleSet usado en esta revisión en la biblioteca local."
        )
        save_row.addWidget(QLabel("Preset:"))
        save_row.addWidget(self.save_preset_name, 1)
        save_row.addWidget(self.save_preset_btn)

        layout.addWidget(title)
        layout.addWidget(self.summary)
        layout.addWidget(hint)
        layout.addWidget(self.tree, 1)
        layout.addLayout(save_row)
        layout.addWidget(self.open_folder_after)

    @staticmethod
    def _destination_group_key(op: Any) -> str:
        if op.destination is None:
            return "(sin destino / error)"
        try:
            return str(Path(op.destination).parent)
        except Exception:
            return str(op.destination)

    def load_operations(
        self,
        operations: list[Any],
        scanned: int | None = None,
    ) -> None:
        self._operations = list(operations)
        self._groups = {}
        self.tree.clear()

        for index, op in enumerate(operations):
            key = self._destination_group_key(op)
            self._groups.setdefault(key, []).append(index)

        # Largest groups first — easier to scan cascade results.
        ordered = sorted(
            self._groups.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )

        for dest_key, indices in ordered:
            status_counts = Counter(operations[i].status for i in indices)
            rule_counts = Counter(operations[i].rule_id for i in indices)
            rules_label = ", ".join(
                f"{rid}×{n}" for rid, n in rule_counts.most_common(3)
            )
            result_parts = []
            for status, n in status_counts.most_common():
                glyph = STATUS_GLYPHS.get(status, "•")
                result_parts.append(f"{n} {glyph}")

            parent = QTreeWidgetItem(
                [
                    f"{elide_middle(safe_display(dest_key), 72)}  ({len(indices)})",
                    rules_label,
                    " · ".join(result_parts),
                    "",
                ]
            )
            parent.setData(0, _OP_INDEX_ROLE, dest_key)
            parent.setToolTip(0, safe_display(dest_key))
            parent.setExpanded(False)

            # Placeholder so expand arrow shows; children load on expand.
            placeholder = QTreeWidgetItem(["…", "", "", ""])
            placeholder.setData(0, _PLACEHOLDER_ROLE, "placeholder")
            parent.addChild(placeholder)
            self.tree.addTopLevelItem(parent)

        ready = sum(
            1
            for op in operations
            if op.status in {"planned", "dry-run", "done", "manual"}
        )
        needs_review = sum(1 for op in operations if op.status == "error")
        ignored = sum(
            1 for op in operations if op.status in {"skipped", "noop"}
        )

        lines = [
            f"✓  {ready} se organizarán / se organizaron / manual",
            f"⚠  {needs_review} requieren revisión",
            f"○  {ignored} se ignorarán / se ignoraron",
            f"📁 {len(self._groups)} carpetas destino",
        ]

        counts = Counter(op.status for op in operations)
        detail = " | ".join(
            f"{status}: {count}" for status, count in counts.items()
        )
        if detail:
            lines.append(detail)

        if scanned is not None:
            lines.insert(0, f"Archivos escaneados: {scanned}")

        if not operations:
            self.summary.setText(
                "Sin operaciones planificadas. Ajusta condiciones o carpeta origen."
            )
        else:
            self.summary.setText("\n".join(lines))

    def _populate_group_children(self, item: QTreeWidgetItem) -> None:
        if item.parent() is not None:
            return

        if item.childCount() == 1:
            child = item.child(0)
            if child.data(0, _PLACEHOLDER_ROLE) != "placeholder":
                return
        elif item.childCount() > 0:
            return

        dest_key = item.data(0, _OP_INDEX_ROLE)
        indices = self._groups.get(str(dest_key), [])
        item.takeChildren()

        for op_index in indices[: self.MAX_CHILDREN_PER_GROUP]:
            op = self._operations[op_index]
            why = "; ".join(op.explanations)
            if op.error:
                why = f"{why} | error: {op.error}" if why else f"error: {op.error}"

            glyph = STATUS_GLYPHS.get(op.status, "•")
            name = Path(op.source).name if op.source else "?"
            child = QTreeWidgetItem(
                [
                    f"{glyph} {elide_middle(safe_display(name), 56)}",
                    str(op.rule_id),
                    str(op.status),
                    elide_middle(why, 80),
                ]
            )
            child.setData(0, _OP_INDEX_ROLE, op_index)
            child.setToolTip(0, safe_display(op.source))
            if op.destination is not None:
                child.setToolTip(0, safe_display(op.source) + "\n→ " + safe_display(op.destination))
            child.setToolTip(3, why)
            if op.status in {"error", "skipped"}:
                brush = QBrush(QColor(ALERT))
            elif op.status in {"planned", "dry-run", "done", "manual"}:
                brush = QBrush(QColor(SUCCESS))
            else:
                brush = QBrush(QColor(MUTED))
            for col in range(4):
                child.setForeground(col, brush)
            item.addChild(child)

        if len(indices) > self.MAX_CHILDREN_PER_GROUP:
            more = QTreeWidgetItem(
                [
                    f"… y {len(indices) - self.MAX_CHILDREN_PER_GROUP} más",
                    "",
                    "",
                    "",
                ]
            )
            item.addChild(more)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is None:
            return
        op_index = item.data(0, _OP_INDEX_ROLE)
        if isinstance(op_index, int):
            self.open_preview.emit(op_index)


class WizardDialog(QDialog):
    def __init__(
        self,
        intent: Intent,
        state_dir: Path,
        parent=None,
    ):
        super().__init__(parent)

        self.intent = intent
        self.state_dir = state_dir

        self.operations: list[Any] = []
        self.scanned = 0
        self.worker = None

        self.setWindowTitle(intent.title)
        self.resize(1100, 720)

        layout = QVBoxLayout(self)

        header = QLabel(intent.description)
        header.setObjectName("muted")
        header.setWordWrap(True)

        steps_row = QHBoxLayout()
        self._step_labels: list[QLabel] = []
        for caption in _WIZARD_STEPS:
            lbl = QLabel(caption)
            lbl.setObjectName("stepIdle")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._step_labels.append(lbl)
            steps_row.addWidget(lbl)

        # I9: persistent remote-endpoint indicator (settings-save modal
        # alone is easy to miss once configured).
        try:
            from ..perception.config import load_perception_config
            from ..perception.http_openai import remote_perception_endpoints

            _remote = remote_perception_endpoints(
                load_perception_config(state_dir=state_dir)
            )
        except Exception:
            _remote = []
        if _remote:
            remote_banner = QLabel(
                "⚠ Las imágenes se enviarán fuera de este equipo: "
                + ", ".join(_remote)
            )
            remote_banner.setObjectName("alert")
            remote_banner.setWordWrap(True)
            layout.addWidget(remote_banner)

        self.stack = QStackedWidget()

        self.page_source = SourcePage(intent)
        self.page_conditions = ConditionsPage(intent)
        self.page_action = ActionPage(intent)
        self.page_review = ReviewPage()
        self.is_cascade = bool(intent.rules_file or intent.preset_name)

        self.stack.addWidget(self.page_source)
        self.stack.addWidget(self.page_conditions)
        self.stack.addWidget(self.page_action)
        self.stack.addWidget(self.page_review)

        self.page_review.open_preview.connect(self.show_preview_dialog)
        self.page_review.save_preset_btn.clicked.connect(self.save_current_as_preset)

        if self.is_cascade:
            source_label = intent.preset_name or intent.rules_file or "ruleset"
            header.setText(
                f"{intent.description}\n\n"
                f"Modo cascada / preset: «{source_label}» "
                "(varias reglas con prioridad). Solo eliges carpeta origen."
            )

        self.status_label = QLabel("Listo")

        self.btn_back = QPushButton("Atrás")
        self.btn_back.setAccessibleName("Atrás")
        self.btn_next = QPushButton("Siguiente")
        self.btn_next.setObjectName("btnPrimary")
        self.btn_next.setAccessibleName("Siguiente")
        self.btn_next.setDefault(True)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setAccessibleName("Cancelar")
        self.btn_stop = QPushButton("Detener")
        self.btn_stop.setAccessibleName("Detener")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Cancela el escaneo o la aplicación en curso")

        self.btn_back.clicked.connect(self.back_pressed)
        self.btn_next.clicked.connect(self.next_pressed)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_stop.clicked.connect(self.stop_worker)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.status_label)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.btn_stop)
        buttons_layout.addWidget(self.btn_cancel)
        buttons_layout.addWidget(self.btn_back)
        buttons_layout.addWidget(self.btn_next)

        layout.addWidget(header)
        layout.addLayout(steps_row)
        layout.addWidget(self.stack)
        layout.addLayout(buttons_layout)

        self.stack.currentChanged.connect(lambda _: self.update_ui())
        self.update_ui()

    def save_current_as_preset(self) -> None:
        name = self.page_review.save_preset_name.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "FileWizard",
                "Escribe un nombre para el preset.",
            )
            return
        try:
            from ..presets import presets_dir, slugify

            if (presets_dir(self.state_dir) / f"{slugify(name)}.yaml").exists():
                answer = QMessageBox.question(
                    self,
                    "FileWizard",
                    f"El preset «{name}» ya existe. Sobrescribir?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        except Exception:
            pass
        try:
            from ..presets import save_preset
            from .workers import ruleset_from_options

            options = self.build_options()
            ruleset = ruleset_from_options(options)
            path = save_preset(
                name,
                ruleset,
                self.state_dir,
                description=self.intent.title,
                overwrite=True,
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "FileWizard", f"No se pudo guardar el preset:\n{exc}"
            )
            return

        QMessageBox.information(
            self,
            "FileWizard",
            f"Preset guardado:\n{path}\n\n"
            f"CLI: filewizard run --source DIR --preset {name}",
        )

    def show_preview_dialog(self, row: int) -> None:
        if row >= len(self.operations):
            return

        op = self.operations[row]
        path = op.source
        # After a prior move the file may already be at destination.
        if not path.exists() and op.destination is not None:
            path = Path(op.destination)
        if not path.exists():
            QMessageBox.warning(
                self,
                "FileWizard",
                "El archivo ya no está disponible para vista previa.",
            )
            return

        dialog = PreviewDialog(
            path=path,
            state_dir=self.state_dir,
            explanations=op.explanations,
            parent=self,
        )
        dialog.exec()

        if dialog.moved_to is not None:
            op.status = "manual"
            op.destination = dialog.moved_to
            self.page_review.load_operations(self.operations, self.scanned)
            self.update_ui()

    def update_ui(self) -> None:
        index = self.stack.currentIndex()

        self.btn_back.setEnabled(index > 0 and self.worker is None)
        self.btn_cancel.setEnabled(self.worker is None)
        self.btn_stop.setEnabled(self.worker is not None)

        if self.is_cascade and index == 0:
            self.btn_next.setText("Revisar cascada")
            self.btn_next.setEnabled(self.worker is None)
        elif index == 2:
            self.btn_next.setText("Revisar")
            self.btn_next.setEnabled(self.worker is None)
        elif index == 3:
            planned = sum(
                1 for op in self.operations if op.status == "planned"
            )
            self.btn_next.setText(f"Aplicar {planned}" if planned else "Aplicar")
            self.btn_next.setEnabled(self.worker is None and planned > 0)
        else:
            self.btn_next.setText("Siguiente")
            self.btn_next.setEnabled(self.worker is None)

        self._refresh_steps(index)

    def _refresh_steps(self, current: int) -> None:
        for i, lbl in enumerate(self._step_labels):
            skipped = self.is_cascade and i in {1, 2}
            if skipped:
                lbl.setObjectName("stepIdle")
                lbl.setEnabled(False)
            elif i < current:
                lbl.setObjectName("stepDone")
                lbl.setEnabled(True)
            elif i == current:
                lbl.setObjectName("stepActive")
                lbl.setEnabled(True)
            else:
                lbl.setObjectName("stepIdle")
                lbl.setEnabled(True)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def build_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}

        options.update(self.page_source.options())

        options["state_dir"] = str(self.state_dir)

        if self.is_cascade:
            if self.intent.preset_name:
                options["preset_name"] = self.intent.preset_name
            if self.intent.rules_file:
                options["rules_file"] = self.intent.rules_file
            options["rule_name"] = self.intent.title
            return options

        options.update(self.page_conditions.options())
        options.update(self.page_action.options())
        options["rule_name"] = self.intent.title

        return options

    def stop_worker(self) -> None:
        if self.worker is not None and hasattr(self.worker, "request_cancel"):
            self.worker.request_cancel()
            self.status_label.setText("Cancelando…")

    def _go_to_review_and_preview(self) -> None:
        self.operations = []
        self.scanned = 0
        self.page_review.load_operations([], None)
        self.stack.setCurrentIndex(3)
        self.start_preview()

    def next_pressed(self) -> None:
        if self.worker is not None:
            return

        index = self.stack.currentIndex()

        if index == 0:
            if not self.page_source.validate():
                return
            if self.is_cascade:
                self._go_to_review_and_preview()
            else:
                self.stack.setCurrentIndex(1)

        elif index == 1:
            if not self.page_conditions.validate():
                return
            self.stack.setCurrentIndex(2)

        elif index == 2:
            if not self.page_action.validate():
                return
            self._go_to_review_and_preview()

        elif index == 3:
            self.apply_pressed()

        self.update_ui()

    def back_pressed(self) -> None:
        if self.worker is not None:
            return

        index = self.stack.currentIndex()

        if index == 3:
            self.operations = []
            self.scanned = 0
            self.page_review.load_operations([], None)
            # Cascade mode: back from review returns to source only.
            if self.is_cascade:
                self.stack.setCurrentIndex(0)
                self.update_ui()
                return

        if index > 0:
            self.stack.setCurrentIndex(index - 1)

        self.update_ui()

    def start_preview(self) -> None:
        options = self.build_options()

        if options.get("ocr_contains_any") and not options.get("enable_ocr"):
            reply = QMessageBox.question(
                self,
                "FileWizard",
                "Hay condiciones OCR pero OCR está desactivado.\n\n"
                "¿Quieres activar OCR para esta ejecución?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.page_source.enable_ocr.setChecked(True)
                options["enable_ocr"] = True

        self.status_label.setText("Generando vista previa...")
        self.update_ui()

        self.worker = PreviewWorker(
            options=options,
            state_dir=self.state_dir,
            parent=self,
        )
        self.worker.progress.connect(self.on_preview_progress)
        self.worker.done.connect(self.on_preview_done)
        self.worker.start()

    def on_preview_progress(self, scanned: int, limit: object) -> None:
        if limit:
            self.status_label.setText(f"Escaneando… {scanned}/{limit}")
        else:
            self.status_label.setText(f"Escaneando… {scanned} archivos")

    def on_preview_done(
        self,
        operations: list[Any],
        scanned: int,
        error: str,
    ) -> None:
        if self.worker is not None:
            self.worker.deleteLater()

        self.worker = None

        if error == "cancelado":
            self.status_label.setText("Vista previa cancelada")
            self.update_ui()
            return

        if error:
            self.status_label.setText("Error en vista previa")
            QMessageBox.critical(
                self,
                "FileWizard",
                f"Error generando la vista previa:\n\n{error}",
            )
            if not self.is_cascade:
                self.stack.setCurrentIndex(2)
            else:
                self.stack.setCurrentIndex(0)
        else:
            self.operations = operations
            self.scanned = scanned
            self.page_review.load_operations(operations, scanned)
            from ..review_queue import ReviewQueue

            pending = len(ReviewQueue(state_dir=self.state_dir).pending())
            if pending:
                self.status_label.setText(
                    f"Vista previa lista · {pending} en cola de revisión"
                )
            else:
                self.status_label.setText("Vista previa lista")

        self.update_ui()

    def apply_pressed(self) -> None:
        planned = [
            op for op in self.operations if op.status == "planned"
        ]

        if not planned:
            QMessageBox.information(
                self,
                "FileWizard",
                "No hay operaciones planificadas para aplicar.",
            )
            return

        message = (
            f"Se van a aplicar {len(planned)} operaciones.\n\n"
            "Esto puede mover o renombrar archivos.\n\n"
            "¿Continuar?"
        )

        reply = QMessageBox.question(
            self,
            "Confirmar",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.status_label.setText("Aplicando operaciones...")
        self.update_ui()

        # Only pass planned ops; re-plan status must remain planned.
        self.worker = ExecuteWorker(
            operations=planned,
            state_dir=self.state_dir,
            parent=self,
        )
        self.worker.progress.connect(self.on_execute_progress)
        self.worker.done.connect(self.on_execute_done)
        self.worker.start()

    def on_execute_progress(self, done: int, total: int) -> None:
        self.status_label.setText(f"Aplicando… {done}/{total}")

    def on_execute_done(
        self,
        results: list[Any],
        error: str,
    ) -> None:
        if self.worker is not None:
            self.worker.deleteLater()

        self.worker = None

        if error == "cancelado":
            self.status_label.setText("Aplicación cancelada (parcial en journal)")
            self.update_ui()
            return

        if error:
            self.status_label.setText("Error durante la ejecución")
            QMessageBox.critical(
                self,
                "FileWizard",
                f"Error ejecutando operaciones:\n\n{error}",
            )
        else:
            self.operations = results
            self.page_review.load_operations(results, self.scanned)

            counts = Counter(op.status for op in results)
            lines = [f"{status}: {count}" for status, count in counts.items()]

            QMessageBox.information(
                self,
                "FileWizard",
                "Operación completada.\n\n"
                + "\n".join(lines)
                + "\n\nPuedes deshacer desde el Journal de la ventana principal.",
            )

            if self.page_review.open_folder_after.isChecked():
                self._open_result_folders(results)

            self.accept()

        self.update_ui()

    def _open_result_folders(self, results: list[Any]) -> None:
        """Open unique destination parent folders after a successful apply."""
        parents: set[Path] = set()
        for op in results:
            if op.status == "done" and op.destination is not None:
                parents.add(Path(op.destination).parent)
        for folder in sorted(parents):
            if folder.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            from .util import abandon_busy_close

            abandon_busy_close(
                self,
                self.worker,
                event,
                busy_text="Hay una operación en curso.",
            )
            if event.isAccepted():
                self.worker = None
            return

        super().closeEvent(event)
