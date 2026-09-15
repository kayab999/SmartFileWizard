from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..executor import PlannedOperation, append_unique
from ..facts import collect_facts
from ..template import render_path_template
from .util import human_size, safe_display
from .workers import ExecuteWorker

DEFAULT_GROUPS = [
    "~/Pictures/Screenshots/{year}/{month}",
    "~/Pictures/Camera/{year}/{month}",
    "~/Pictures/Photos/{year}/{month}",
    "~/Pictures/Social/{year}",
    "~/Documents/Scans/{year}",
    "~/Pictures/Misc/{year}/{month}",
]


def load_thumbnail(path: Path, max_size: int = 320):
    """R11: bounded decode; never full-resolution for a thumbnail."""
    try:
        reader = QImageReader(str(path))
        if hasattr(reader, "setAllocationLimit"):
            reader.setAllocationLimit(256)  # MB

        original = reader.size()
        if original.isValid():
            reader.setScaledSize(
                original.scaled(QSize(max_size, max_size), Qt.KeepAspectRatio)
            )

        image = reader.read()
        if image.isNull():
            return None, reader.errorString()
        return QPixmap.fromImage(image), None
    except Exception as exc:
        return None, str(exc)


class PreviewDialog(QDialog):
    def __init__(
        self,
        path: Path,
        state_dir: Path,
        explanations: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)

        self.path = path
        self.state_dir = state_dir
        self.worker = None
        self.moved_to = None

        self.setWindowTitle(safe_display(path.name))
        self.resize(760, 540)

        layout = QVBoxLayout(self)
        content = QHBoxLayout()

        self.thumb_label = QLabel("Cargando…")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setMinimumSize(340, 340)

        try:
            from ..plugins.heuristics import ImageHeuristics

            self.facts = collect_facts(path, extractors=[ImageHeuristics()])
        except Exception:
            self.facts = None

        details = QFormLayout()

        if self.facts is not None:
            f = self.facts
            details.addRow("Nombre", QLabel(safe_display(f.filename)))
            details.addRow("Ruta", QLabel(safe_display(f.path.parent)))
            details.addRow("Tamaño", QLabel(human_size(f.size)))
            details.addRow("Tipo", QLabel(f.mime))
            if f.width:
                details.addRow("Dimensiones", QLabel(f"{f.width}×{f.height}"))
            taken = f.features.get("date_taken")
            if taken:
                details.addRow(
                    "Fecha",
                    QLabel(f"{taken} ({f.features.get('date_source')})"),
                )
            exif = f.features.get("exif", {})
            if isinstance(exif, dict) and (exif.get("make") or exif.get("model")):
                details.addRow(
                    "Cámara",
                    QLabel(f"{exif.get('make', '')} {exif.get('model', '')}".strip()),
                )
            if isinstance(exif, dict) and exif.get("software"):
                details.addRow("Software", QLabel(str(exif["software"])))
            pats = f.features.get("filename_patterns")
            if pats:
                details.addRow("Patrones", QLabel(", ".join(pats)))
            uc = f.features.get("unique_colors")
            if uc is not None:
                details.addRow("Paleta", QLabel(f"{uc} colores (thumb 48×48)"))
            cascade = f.features.get("cascade")
            if isinstance(cascade, dict) and cascade.get("category"):
                from ..perception.snapshot import format_perception_evidence
                from ..perception.snapshot import perception_snapshot

                ev = format_perception_evidence(perception_snapshot(f.features))
                if ev:
                    details.addRow("Cascada", QLabel(ev))
        else:
            details.addRow("Error", QLabel("No se pudieron leer los metadatos."))

        if explanations:
            details.addRow("Motivo", QLabel("; ".join(explanations)))

        content.addWidget(self.thumb_label)
        content.addLayout(details)
        layout.addLayout(content, 1)

        move_layout = QHBoxLayout()
        move_layout.addWidget(QLabel("Mover a:"))

        self.group_combo = QComboBox()
        self._last_index = 0
        self._fill_combo()
        self.group_combo.currentIndexChanged.connect(self._on_combo_changed)
        move_layout.addWidget(self.group_combo, 1)

        self.move_button = QPushButton("Mover aquí")
        self.move_button.setEnabled(self.facts is not None and self.path.exists())
        self.move_button.clicked.connect(self._move_here)
        move_layout.addWidget(self.move_button)

        layout.addLayout(move_layout)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self._load_thumbnail()

    def _load_thumbnail(self) -> None:
        pixmap, error = load_thumbnail(self.path)
        if pixmap is None:
            self.thumb_label.setText(f"Sin vista previa\n{error or ''}")
        else:
            self.thumb_label.setPixmap(pixmap)

    def _fill_combo(self) -> None:
        self.group_combo.clear()
        if self.facts is None:
            for template in DEFAULT_GROUPS:
                self.group_combo.addItem(template, template)
        else:
            for template in DEFAULT_GROUPS:
                try:
                    rendered = render_path_template(template, self.facts)
                except Exception:
                    rendered = Path(template)
                self.group_combo.addItem(safe_display(rendered), template)
        self.group_combo.addItem("— Otra carpeta… —", "__custom__")

    def _on_combo_changed(self, index: int) -> None:
        if self.group_combo.currentData() == "__custom__":
            directory = QFileDialog.getExistingDirectory(
                self, "Seleccionar carpeta destino"
            )
            if directory:
                custom_index = self.group_combo.count() - 1
                self.group_combo.insertItem(custom_index, directory, directory)
                self.group_combo.setCurrentIndex(custom_index)
            else:
                self.group_combo.setCurrentIndex(self._last_index)
        self._last_index = self.group_combo.currentIndex()

    def _move_here(self) -> None:
        if self.worker is not None or self.facts is None:
            return

        data = self.group_combo.currentData()
        try:
            if data and data != "__custom__" and "{" in str(data):
                target_dir = render_path_template(str(data), self.facts)
            else:
                target_dir = Path(self.group_combo.currentText()).expanduser()
        except Exception as exc:
            QMessageBox.critical(self, "FileWizard", str(exc))
            return

        if not target_dir.is_absolute():
            QMessageBox.critical(
                self, "FileWizard", "La carpeta destino debe ser absoluta."
            )
            return

        destination = target_dir / self.path.name

        if destination.resolve() == self.path.resolve():
            self.status_label.setText("El archivo ya está en ese destino.")
            return

        if destination.exists():
            destination = append_unique(destination)

        op = PlannedOperation(
            source=self.path,
            rule_id="manual",
            rule_name="Movido manualmente",
            destination=destination,
            explanations=["movido manualmente desde la vista previa"],
            create_target_dir=True,
            on_collision="append",
            status="planned",
        )

        self.move_button.setEnabled(False)
        self.status_label.setText("Moviendo…")

        self.worker = ExecuteWorker([op], self.state_dir, self)
        self.worker.done.connect(self._on_move_done)
        self.worker.start()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        worker = getattr(self, "worker", None)
        running = False
        if worker is not None:
            try:
                running = worker.isRunning()
            except RuntimeError:
                running = False
        if running:
            from .util import abandon_busy_close

            abandon_busy_close(
                self,
                worker,
                event,
                busy_text="Hay un movimiento en curso.",
            )
            if event.isAccepted():
                self.worker = None
            return
        super().closeEvent(event)

    def _on_move_done(self, results, error) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.move_button.setEnabled(True)

        if error or not results or results[0].status != "done":
            detail = error or (results[0].error if results else "sin resultado")
            self.status_label.setText(f"Error: {detail}")
        else:
            self.moved_to = results[0].destination
            self.status_label.setText(
                f"✓ Movido a {safe_display(self.moved_to)}"
            )
