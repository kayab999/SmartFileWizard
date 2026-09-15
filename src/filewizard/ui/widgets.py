"""Small styled widgets for home (no filesystem logic)."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from .theme import ALERT, TEXT


class IntentCard(QPushButton):
    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("intentCard")
        self.setAccessibleName(title)
        self.setToolTip(description)
        self.setText(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class BadgeButton(QPushButton):
    """Toolbar button with an optional amber numeric badge."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._badge = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_badge(self, text: str) -> None:
        self._badge = text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._badge:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(max(8, self.font().pointSize() - 2))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pad = 4
        w = max(18, metrics.horizontalAdvance(self._badge) + pad * 2)
        h = max(18, metrics.height() + 2)
        rect = QRect(self.width() - w - 4, 4, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ALERT))
        painter.drawRoundedRect(rect, h / 2, h / 2)
        painter.setPen(QColor("#1A1A1D"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._badge)
        painter.end()


class BatchCard(QFrame):
    undo_requested = Signal(str)

    def __init__(
        self,
        batch_id: str,
        title: str,
        dest: str,
        counts: str,
        *,
        can_undo: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("batchCard")
        self.batch_id = batch_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        row = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        undo_btn = QPushButton("Deshacer")
        undo_btn.setObjectName("btnFlat")
        undo_btn.setEnabled(can_undo)
        undo_btn.setAccessibleName("Deshacer lote")
        undo_btn.clicked.connect(lambda: self.undo_requested.emit(self.batch_id))
        row.addWidget(title_lbl, 1)
        row.addWidget(undo_btn)
        dest_lbl = QLabel(dest)
        dest_lbl.setObjectName("muted")
        dest_lbl.setWordWrap(True)
        counts_lbl = QLabel(counts)
        counts_lbl.setStyleSheet(f"color: {TEXT};")
        layout.addLayout(row)
        layout.addWidget(dest_lbl)
        layout.addWidget(counts_lbl)
