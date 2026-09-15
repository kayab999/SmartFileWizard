from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..presets import ensure_builtin_presets, list_presets
from ..watch import (
    ActiveWatch,
    WatchError,
    add_active_watch,
    load_active_watches,
    remove_active_watch,
)


class WatchDialog(QDialog):
    """List / add / remove active watches and run a single tick (WP-0.8.7)."""

    def __init__(self, state_dir: Path, parent=None):
        super().__init__(parent)
        self.state_dir = state_dir
        self.worker = None
        self.setWindowTitle("Vigilancia de carpetas")
        self.resize(720, 420)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Un tick aplica el preset a la carpeta (dry-run por defecto). "
            "El bucle --interval sigue siendo CLI."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 4)
        self.table.setAccessibleName("Watches activos")
        self.table.setHorizontalHeaderLabels(
            ["Nombre", "Origen", "Preset/reglas", "Dry-run"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 280)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setAccessibleName("Nombre del watch")
        self.source_edit = QLineEdit()
        self.source_edit.setAccessibleName("Carpeta a vigilar")
        browse = QPushButton("Examinar…")
        browse.clicked.connect(self._browse)
        src_row = QHBoxLayout()
        src_row.addWidget(self.source_edit, 1)
        src_row.addWidget(browse)
        self.preset_combo = QComboBox()
        self.preset_combo.setAccessibleName("Preset del watch")
        ensure_builtin_presets(self.state_dir)
        for item in list_presets(self.state_dir):
            self.preset_combo.addItem(item.name, item.name)
        self.dry_run = QCheckBox("Solo vista previa (dry-run)")
        self.dry_run.setChecked(True)
        self.dry_run.setAccessibleName("Solo vista previa")
        form.addRow("Nombre", self.name_edit)
        form.addRow("Carpeta", src_row)
        form.addRow("Preset", self.preset_combo)
        form.addRow(self.dry_run)
        layout.addLayout(form)

        row = QHBoxLayout()
        add_btn = QPushButton("Añadir")
        add_btn.setAccessibleName("Añadir watch")
        add_btn.clicked.connect(self.add_watch)
        rm_btn = QPushButton("Quitar")
        rm_btn.setAccessibleName("Quitar watch seleccionado")
        rm_btn.clicked.connect(self.remove_selected)
        run_btn = QPushButton("Ejecutar tick")
        run_btn.setAccessibleName("Ejecutar tick del watch seleccionado")
        run_btn.clicked.connect(self.run_tick)
        row.addWidget(add_btn)
        row.addWidget(rm_btn)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)

        self.status = QLabel("")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.reload()

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Carpeta a vigilar", str(Path.home())
        )
        if directory:
            self.source_edit.setText(directory)

    def reload(self) -> None:
        watches = load_active_watches(self.state_dir)
        self.table.setRowCount(0)
        for w in watches:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(w.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(w.source)))
            spec = w.preset or (str(w.rules) if w.rules else "")
            self.table.setItem(row, 2, QTableWidgetItem(spec))
            self.table.setItem(row, 3, QTableWidgetItem("sí" if w.dry_run else "no"))

    def add_watch(self) -> None:
        name = self.name_edit.text().strip()
        source = self.source_edit.text().strip()
        preset = str(self.preset_combo.currentData() or "")
        if not name or not source or not preset:
            QMessageBox.information(
                self, "FileWizard", "Nombre, carpeta y preset son obligatorios."
            )
            return
        try:
            add_active_watch(
                self.state_dir,
                ActiveWatch(
                    name=name,
                    source=Path(source),
                    preset=preset,
                    dry_run=self.dry_run.isChecked(),
                ),
            )
        except WatchError as exc:
            QMessageBox.warning(self, "FileWizard", str(exc))
            return
        self.reload()

    def _selected_name(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    def remove_selected(self) -> None:
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, "FileWizard", "Selecciona un watch.")
            return
        answer = QMessageBox.question(
            self,
            "FileWizard",
            f"Quitar el watch «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_active_watch(self.state_dir, name)
        except WatchError as exc:
            QMessageBox.warning(self, "FileWizard", str(exc))
            return
        self.reload()

    def run_tick(self) -> None:
        from .workers import WatchTickWorker

        name = self._selected_name()
        watches = load_active_watches(self.state_dir)
        if name:
            watch = next((w for w in watches if w.name == name), None)
        else:
            watch = None
        if watch is None:
            QMessageBox.information(
                self, "FileWizard", "Selecciona un watch para el tick."
            )
            return
        if getattr(self, "worker", None) is not None:
            return
        self._tick_name = watch.name
        self._tick_dry = watch.dry_run
        self.status.setText(f"Ejecutando tick «{watch.name}»…")
        self.worker = WatchTickWorker(watch.to_watch_config(self.state_dir), parent=self)
        self.worker.done.connect(self._on_tick_done)
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
                busy_text="Hay un tick de vigilancia en curso.",
            )
            if event.isAccepted():
                self.worker = None
            return
        super().closeEvent(event)

    def _on_tick_done(self, ops, scanned: int, error: str) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if error:
            QMessageBox.critical(self, "FileWizard", error)
            self.status.setText("Tick falló")
            return
        name = getattr(self, "_tick_name", "")
        dry = getattr(self, "_tick_dry", True)
        self.status.setText(
            f"Tick «{name}»: {scanned} escaneados, {len(ops)} operaciones "
            f"({'dry-run' if dry else 'aplicado'})."
        )
