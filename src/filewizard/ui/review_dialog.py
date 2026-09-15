from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..perception.cascade import DEFAULT_LABELS
from ..review_queue import ReviewQueue


class ReviewQueueDialog(QDialog):
    """Manual classification queue for cascade unknown / low-confidence files."""

    def __init__(self, state_dir: Path, parent=None):
        super().__init__(parent)
        self.state_dir = state_dir
        self.queue = ReviewQueue(state_dir=state_dir)
        self.setWindowTitle("Cola de revisión manual")
        self.resize(820, 480)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Archivos con cascada status=unknown/rejected o probable de baja "
            "confianza. Asigna una categoría o descarta. Se rellena al hacer "
            "vista previa en el wizard."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Archivo", "Hint", "Conf.", "Status", "Motivo"]
        )
        self.table.setAccessibleName("Cola de revisión")
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Fase 3: multi-selección para triaje en lote (resolve/dismiss).
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 90)
        self.table.itemSelectionChanged.connect(self._update_thumb)
        self.table.itemDoubleClicked.connect(self._open_preview)
        # Keyboard Enter opens the preview for the focused row.
        self.table.itemActivated.connect(self._open_preview)
        layout.addWidget(self.table)

        self.thumb_label = QLabel("Selecciona un archivo para miniatura")
        self.thumb_label.setMinimumHeight(120)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumb_label)

        row = QHBoxLayout()
        self.category = QComboBox()
        self.category.setAccessibleName("Categoría a asignar")
        for lab in DEFAULT_LABELS:
            self.category.addItem(lab, lab)
        self.category.addItem("otro / dismiss", "dismissed")
        row.addWidget(QLabel("Categoría:"))
        row.addWidget(self.category, 1)

        resolve_btn = QPushButton("Asignar")
        resolve_btn.setAccessibleName("Asignar categoría a la selección")
        resolve_btn.clicked.connect(self.resolve_selected)
        dismiss_btn = QPushButton("Descartar")
        dismiss_btn.setAccessibleName("Descartar selección")
        dismiss_btn.clicked.connect(self.dismiss_selected)
        clear_btn = QPushButton("Limpiar resueltos")
        clear_btn.setAccessibleName("Limpiar resueltos")
        clear_btn.clicked.connect(self.clear_resolved)
        refresh_btn = QPushButton("Refrescar")
        refresh_btn.setAccessibleName("Refrescar cola")
        refresh_btn.clicked.connect(self.reload)
        export_btn = QPushButton("Exportar labels JSON…")
        export_btn.setAccessibleName("Exportar labels JSON")
        export_btn.setToolTip(
            "Exporta pendientes+resueltos en formato --agent-features / MCP"
        )
        export_btn.clicked.connect(self.export_labels)

        row.addWidget(resolve_btn)
        row.addWidget(dismiss_btn)
        row.addWidget(clear_btn)
        row.addWidget(refresh_btn)
        row.addWidget(export_btn)
        layout.addLayout(row)

        self.count_label = QLabel("")
        layout.addWidget(self.count_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.reload()

    def reload(self) -> None:
        self.queue.load()
        pending = self.queue.pending()
        self.table.setRowCount(0)
        for item in pending:
            row = self.table.rowCount()
            self.table.insertRow(row)
            path_item = QTableWidgetItem(item.path)
            path_item.setData(Qt.ItemDataRole.UserRole, item.id)
            path_item.setToolTip(item.path)
            self.table.setItem(row, 0, path_item)
            self.table.setItem(row, 1, QTableWidgetItem(item.category_hint))
            self.table.setItem(
                row, 2, QTableWidgetItem(f"{item.confidence:.2f}")
            )
            self.table.setItem(row, 3, QTableWidgetItem(item.status))
            self.table.setItem(row, 4, QTableWidgetItem(item.reason[:80]))
        total = len(self.queue.items)
        resolved = total - len(pending)
        msg = (
            f"Pendientes: {len(pending)} · Resueltos: {resolved} · Total: {total}"
        )
        if self.queue.load_error:
            msg += f" · aviso: cola corrupta (respaldo .bak) — {self.queue.load_error[:80]}"
        self.count_label.setText(msg)

    def _selected_ids(self) -> list[str]:
        rows = self.table.selectionModel().selectedRows()
        ids: list[str] = []
        for row in rows:
            item = self.table.item(row.row(), 0)
            if item is None:
                continue
            value = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if value:
                ids.append(value)
        return ids

    def _selected_id(self) -> str | None:
        ids = self._selected_ids()
        return ids[0] if ids else None

    def resolve_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(
                self, "FileWizard", "Selecciona un archivo de la cola."
            )
            return
        cat = str(self.category.currentData() or "unknown")
        for item_id in ids:
            self.queue.resolve(item_id, cat)
        self.reload()
        QMessageBox.information(
            self,
            "FileWizard",
            "La próxima vista previa usará esta categoría como evidencia.",
        )

    def dismiss_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(
                self, "FileWizard", "Selecciona un archivo de la cola."
            )
            return
        for item_id in ids:
            self.queue.dismiss(item_id)
        self.reload()

    def clear_resolved(self) -> None:
        pending = [i for i in self.queue.items if i.resolved]
        if not pending:
            QMessageBox.information(self, "FileWizard", "No hay resueltos.")
            return
        answer = QMessageBox.question(
            self,
            "FileWizard",
            f"Eliminar {len(pending)} elementos resueltos de la cola?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        n = self.queue.clear_resolved()
        self.reload()
        QMessageBox.information(
            self, "FileWizard", f"Eliminados {n} elementos resueltos."
        )

    def _selected_path(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _update_thumb(self) -> None:
        from .preview_dialog import load_thumbnail

        path_s = self._selected_path()
        if not path_s:
            self.thumb_label.setText("Selecciona un archivo para miniatura")
            return
        path = Path(path_s)
        if not path.is_file():
            self.thumb_label.setText("Archivo no encontrado")
            return
        pix, err = load_thumbnail(path, max_size=160)
        if pix is None:
            self.thumb_label.setText(err or "Sin miniatura")
            return
        self.thumb_label.setPixmap(pix)

    def _open_preview(self) -> None:
        from .preview_dialog import PreviewDialog

        path_s = self._selected_path()
        if not path_s:
            return
        path = Path(path_s)
        if not path.is_file():
            QMessageBox.information(self, "FileWizard", "El archivo ya no existe.")
            return
        PreviewDialog(path, self.state_dir, parent=self).exec()

    def export_labels(self) -> None:
        import json

        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar labels",
            str(self.state_dir / "agent-labels.json"),
            "JSON (*.json)",
        )
        if not dest:
            return
        mapping = self.queue.export_agent_labels()
        from ..persist import atomic_write_text

        atomic_write_text(
            Path(dest),
            json.dumps(mapping, ensure_ascii=False, indent=2),
        )
        QMessageBox.information(
            self, "FileWizard", f"Exportados {len(mapping)} labels a:\n{dest}"
        )
