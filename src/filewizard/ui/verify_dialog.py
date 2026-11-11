"""Dialog for operations pending verification (needs_verify)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from ..journal import Journal


class VerifyDialog(QDialog):
    """List needs_verify operations and offer a verify action."""

    def __init__(self, state_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.state_dir = state_dir
        self.setWindowTitle("Operaciones pendientes de verificación")
        self.resize(640, 360)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Close
        )
        buttons.accepted.connect(self._verify)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()

    def _load(self) -> None:
        journal = Journal(self.state_dir / "journal.db")
        try:
            rows = [
                r for r in journal.recent_operations(200)
                if str(r["status"]) == "needs_verify"
            ]
        finally:
            journal.close()
        for row in rows:
            text = f"[{row['id']}] {row['source']} → {row['destination']}"
            item = QListWidgetItem(text)
            item.setData(1, row["batch_id"])
            self.list.addItem(item)
        if self.list.count() == 0:
            self.list.addItem("No hay operaciones pendientes.")

    def _verify(self) -> None:
        current = self.list.currentItem()
        if current is None:
            return
        batch_id = current.data(1)
        if not batch_id:
            return
        from ..verify_batch import verify_batch

        report = verify_batch(self.state_dir / "journal.db", batch_id)
        QMessageBox.information(
            self,
            "Verificar lote",
            f"Batch {batch_id}: "
            f"holds={report.holds}, divergencias={len(report.divergences)}, "
            f"pendientes={len(report.awaiting_review)}",
        )
        self.list.clear()
        self._load()
