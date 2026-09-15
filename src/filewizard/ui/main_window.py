from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..journal import Journal
from ..presets import ensure_builtin_presets, list_presets
from .intents import INTENTS, Intent
from .util import elide_middle, relative_time
from .widgets import BadgeButton, BatchCard, IntentCard
from .wizard import WizardDialog
from .workers import UndoWorker


class MainWindow(QMainWindow):
    def __init__(
        self,
        state_dir: Path,
        parent=None,
    ):
        super().__init__(parent)

        self.state_dir = state_dir
        self._batches: dict[str, Any] = {}
        self._last_batch_id: str | None = None
        self.undo_worker = None
        self.tray_manager = None
        self._force_quit = False

        self.setWindowTitle("FileWizard")
        self.resize(960, 740)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        title = QLabel("¿Qué quieres hacer?")
        font = title.font()
        font.setPointSize(18)
        font.setBold(True)
        title.setFont(font)

        subtitle = QLabel(
            "Reglas locales, dry-run, journal y undo. "
            "La percepción aporta evidencia; las reglas deciden."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)

        grid = QGridLayout()
        grid.setSpacing(10)

        for index, intent in enumerate(INTENTS):
            button = IntentCard(intent.title, intent.description)
            button.clicked.connect(
                lambda checked=False, intent=intent: self.open_intent(intent)
            )
            row = index // 2
            column = index % 2
            grid.addWidget(button, row, column)

        top_row = QHBoxLayout()
        top_row.addWidget(title, 1)
        self.review_btn = BadgeButton("Cola de revisión")
        self.review_btn.setAccessibleName("Cola de revisión")
        self.review_btn.setToolTip(
            "Archivos unknown / baja confianza de la cascada de percepción"
        )
        self.review_btn.clicked.connect(self.open_review_queue)
        watch_btn = QPushButton("Vigilancia…")
        watch_btn.setAccessibleName("Vigilancia")
        watch_btn.setToolTip("Watches activos: un tick (dry-run o aplicar)")
        watch_btn.clicked.connect(self.open_watch)
        settings_btn = QPushButton("Ajustes…")
        settings_btn.setAccessibleName("Ajustes de percepción")
        settings_btn.setToolTip("Percepción: OCR / visión / modelos / endpoints")
        settings_btn.clicked.connect(self.open_settings)
        support_btn = QPushButton("Apoyar…")
        support_btn.setAccessibleName("Apoyar FileWizard")
        support_btn.setToolTip("Buy Me a Coffee y el repositorio en GitHub")
        support_btn.clicked.connect(self.open_support)
        top_row.addWidget(self.review_btn)
        top_row.addWidget(watch_btn)
        top_row.addWidget(settings_btn)
        top_row.addWidget(support_btn)

        layout.addLayout(top_row)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addLayout(grid)

        # --- Biblioteca de presets ---
        presets_group = QGroupBox("Biblioteca de presets")
        playout = QHBoxLayout(presets_group)
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(220)
        run_preset_btn = QPushButton("Ejecutar preset…")
        run_preset_btn.setObjectName("btnPrimary")
        run_preset_btn.setToolTip(
            "Abre el wizard en modo cascada con el RuleSet del preset."
        )
        run_preset_btn.clicked.connect(self.run_selected_preset)
        refresh_presets_btn = QPushButton("Refrescar")
        refresh_presets_btn.clicked.connect(self.refresh_presets)
        playout.addWidget(self.preset_combo, 1)
        playout.addWidget(run_preset_btn)
        playout.addWidget(refresh_presets_btn)
        layout.addWidget(presets_group)

        # --- Historial por lotes ---
        history_group = QGroupBox("Historial de operaciones")
        hlayout = QVBoxLayout(history_group)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)

        self.banner_label = QLabel("Sin operaciones todavía.")
        self.banner_label.setWordWrap(True)
        self.banner_undo = QPushButton("Deshacer este lote")
        self.banner_undo.setObjectName("btnPrimary")
        self.banner_undo.clicked.connect(self.undo_last_batch)

        banner_layout.addWidget(self.banner_label, 1)
        banner_layout.addWidget(self.banner_undo)

        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setMaximumHeight(280)
        self._batch_host = QWidget()
        self._batch_layout = QVBoxLayout(self._batch_host)
        self._batch_layout.setContentsMargins(0, 0, 0, 0)
        self._batch_layout.setSpacing(8)
        self._batch_layout.addStretch()
        self.history_scroll.setWidget(self._batch_host)

        hbuttons = QHBoxLayout()
        refresh_btn = QPushButton("Refrescar")
        refresh_btn.clicked.connect(self.refresh_journal)
        hbuttons.addWidget(refresh_btn)
        hbuttons.addStretch()

        hlayout.addWidget(self.banner)
        hlayout.addWidget(self.history_scroll)
        hlayout.addLayout(hbuttons)
        layout.addWidget(history_group)

        footer = QLabel(
            "Principio del motor: percepción → evidencia; "
            "reglas → decisión; journal → undo."
        )
        footer.setObjectName("footer")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self._check_pending()
        self.refresh_presets()
        self.refresh_journal()
        self.refresh_review_badge()

    def open_support(self) -> None:
        from .support import open_support_links

        open_support_links(self)

    def open_settings(self) -> None:
        from .settings_dialog import PerceptionSettingsDialog

        dialog = PerceptionSettingsDialog(self.state_dir, parent=self)
        dialog.exec()

    def open_watch(self) -> None:
        from .watch_dialog import WatchDialog

        if self.tray_manager is not None:
            self.tray_manager.set_state_active()
        dialog = WatchDialog(self.state_dir, parent=self)
        dialog.exec()
        self.refresh_journal()
        self.refresh_review_badge()

    def open_review_queue(self) -> None:
        from .review_dialog import ReviewQueueDialog

        dialog = ReviewQueueDialog(self.state_dir, parent=self)
        dialog.exec()
        self.refresh_review_badge()

    def refresh_review_badge(self) -> None:
        from ..review_queue import ReviewQueue

        queue = ReviewQueue(state_dir=self.state_dir)
        self.review_btn.setText("Cola de revisión")
        if queue.load_error:
            self.review_btn.set_badge("!")
            self.review_btn.setToolTip(
                "Cola corrupta: respaldo .bak. Abre el diálogo para detalles."
            )
        else:
            pending = queue.pending()
            self.review_btn.set_badge(str(len(pending)) if pending else "")
            self.review_btn.setToolTip(
                "Archivos unknown / baja confianza de la cascada de percepción"
            )
        self._sync_tray(queue)

    def refresh_presets(self) -> None:
        ensure_builtin_presets(self.state_dir)
        self.preset_combo.clear()
        items = list_presets(self.state_dir)
        if not items:
            self.preset_combo.addItem("(sin presets)", "")
            return
        for item in items:
            label = f"{item.name} ({item.rule_count} reglas)"
            if item.description:
                label = f"{item.name} — {item.description[:40]}"
            self.preset_combo.addItem(label, item.name)

    def run_selected_preset(self) -> None:
        name = self.preset_combo.currentData()
        if not name:
            QMessageBox.information(
                self, "FileWizard", "No hay preset seleccionado."
            )
            return
        intent = Intent(
            id=f"preset:{name}",
            title=f"Preset: {name}",
            description=(
                f"Ejecutar el preset «{name}» desde la biblioteca local "
                f"({self.state_dir / 'presets'})."
            ),
            preset_name=str(name),
        )
        self.open_intent(intent)

    def _sync_tray(self, queue=None) -> None:
        mgr = self.tray_manager
        if mgr is None:
            return
        if self.undo_worker is not None:
            mgr.set_state_active()
            return
        if queue is None:
            from ..review_queue import ReviewQueue

            queue = ReviewQueue(state_dir=self.state_dir)
        if queue.load_error or queue.pending():
            mgr.set_state_alert()
        else:
            mgr.set_state_idle()

    def open_intent(self, intent) -> None:
        if self.tray_manager is not None:
            self.tray_manager.set_state_active()
        dialog = WizardDialog(
            intent=intent,
            state_dir=self.state_dir,
            parent=self,
        )
        dialog.exec()
        self.refresh_presets()
        self.refresh_journal()
        self.refresh_review_badge()

    def _check_pending(self) -> None:
        """R4: recovery for interrupted executions."""
        journal = Journal(self.state_dir / "journal.db")
        try:
            pending = journal.pending_operations()
            if pending:
                reply = QMessageBox.question(
                    self,
                    "FileWizard",
                    f"Hay {len(pending)} operaciones 'pending' de una ejecución "
                    "interrumpida.\n¿Marcarlas como interrumpidas?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    journal.resolve_pending()
        finally:
            journal.close()

    @staticmethod
    def _batch_label(batch) -> str:
        names = [
            n.strip()
            for n in (batch["rule_names"] or "").split(",")
            if n.strip()
        ]
        label = ", ".join(dict.fromkeys(names)) or (batch["ops"] or "operación")
        ops = batch["ops"] or ""
        if "undo" in ops:
            # Avoid "Undo (Undo · …)" when rule_name already says Undo
            if not label.lower().startswith("undo"):
                label = f"Undo ({label})"
        return label

    @staticmethod
    def _batch_counts(batch) -> str:
        parts = []
        done = int(batch["done"] or 0)
        failed = int(batch["failed"] or 0) + int(batch["errors"] or 0)
        skipped = int(batch["skipped"] or 0)
        undone = int(batch["undone"] or 0)
        if done:
            parts.append(f"{done} ✓")
        if failed:
            parts.append(f"{failed} ✕")
        if skipped:
            parts.append(f"{skipped} ⏭")
        if undone:
            parts.append(f"{undone} ↩")
        return " · ".join(parts) or "—"

    def _destination_summary(
        self,
        batch_id: str,
        rows: list[Any] | None = None,
    ) -> str:
        if rows is None:
            journal = Journal(self.state_dir / "journal.db")
            try:
                rows = journal.operations_for_batch(batch_id)
            finally:
                journal.close()

        counts: Counter[str] = Counter()
        for row in rows:
            if row["status"] == "done" and row["destination"]:
                counts[str(Path(row["destination"]).parent)] += 1

        top = counts.most_common(2)
        return " · ".join(
            f"{elide_middle(p, 44)} ({n})" for p, n in top
        ) or "—"

    def refresh_journal(self) -> None:
        journal = Journal(self.state_dir / "journal.db")
        try:
            batches = journal.recent_batches(20)
            # Prefetch destinations only for the latest batch (banner + first row)
            dest_cache: dict[str, str] = {}
            if batches:
                first_id = batches[0]["batch_id"]
                dest_cache[first_id] = self._destination_summary(
                    first_id,
                    journal.operations_for_batch(first_id),
                )
        finally:
            journal.close()

        self._batches = {b["batch_id"]: b for b in batches}
        while self._batch_layout.count() > 1:
            item = self._batch_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for b in batches:
            ops = b["ops"] or ""
            if "undo" in ops:
                glyph = "↩"
            elif int(b["failed"] or 0) or int(b["errors"] or 0) or int(
                b["skipped"] or 0
            ):
                glyph = "⚠"
            else:
                glyph = "✓"

            batch_id = b["batch_id"]
            dest = dest_cache.get(batch_id)
            if dest is None:
                total = int(b["total"] or 0)
                dest = f"{total} archivo(s)" if total else "—"
            title = (
                f"{glyph} {relative_time(b['finished_at'])} · "
                f"{self._batch_label(b)}"
            )
            can_undo = ("move" in ops) and int(b["done"] or 0) > 0
            card = BatchCard(
                batch_id,
                title,
                dest,
                self._batch_counts(b),
                can_undo=can_undo,
            )
            card.undo_requested.connect(self._undo_batch)
            self._batch_layout.insertWidget(self._batch_layout.count() - 1, card)

        if batches:
            last = batches[0]
            self._last_batch_id = last["batch_id"]
            dest = dest_cache.get(last["batch_id"], "—")
            self.banner_label.setText(
                f"Última operación: {relative_time(last['finished_at'])} · "
                f"{self._batch_label(last)} · {self._batch_counts(last)} · "
                f"{dest}"
            )
            self.banner_undo.setEnabled(
                ("move" in (last["ops"] or ""))
                and int(last["done"] or 0) > 0
            )
        else:
            self._last_batch_id = None
            self.banner_label.setText("Sin operaciones todavía.")
            self.banner_undo.setEnabled(False)

    def undo_last_batch(self) -> None:
        if self._last_batch_id is None or self.undo_worker is not None:
            return
        self._undo_batch(self._last_batch_id)

    def _undo_batch(self, batch_id: str) -> None:
        journal = Journal(self.state_dir / "journal.db")
        try:
            rows = journal.done_moves_for_batch(batch_id)
        finally:
            journal.close()

        if not rows:
            QMessageBox.information(
                self, "FileWizard", "Nada que deshacer en este lote."
            )
            return

        reply = QMessageBox.question(
            self,
            "Confirmar undo",
            f"Se desharán {len(rows)} movimientos de este lote.\n¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.undo_worker = UndoWorker(rows, self.state_dir, self)
        self.undo_worker.done.connect(self.on_undo_done)
        if self.tray_manager is not None:
            self.tray_manager.set_state_active()
        self.undo_worker.start()

    def on_undo_done(self, results, error) -> None:
        if self.undo_worker is not None:
            self.undo_worker.deleteLater()
        self.undo_worker = None

        if error:
            QMessageBox.critical(self, "FileWizard", f"Error en undo:\n{error}")
        else:
            counts = Counter(r["status"] for r in results)
            QMessageBox.information(
                self,
                "FileWizard",
                "Undo completado:\n"
                + "\n".join(f"{k}: {v}" for k, v in counts.items()),
            )

        self.refresh_journal()

    def closeEvent(self, event) -> None:
        if self.undo_worker is not None:
            from .util import abandon_busy_close

            abandon_busy_close(
                self,
                self.undo_worker,
                event,
                busy_text="Hay un undo en curso.",
            )
            if event.isAccepted():
                self.undo_worker = None
            return
        if (
            self.tray_manager is not None
            and self.tray_manager.available
            and not self._force_quit
        ):
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)
