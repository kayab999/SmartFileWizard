from __future__ import annotations

from datetime import datetime, timezone


def safe_display(path) -> str:
    """R9: invalid bytes display with replacement; do not crash Qt."""
    return str(path).encode("utf-8", "replace").decode("utf-8")


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def relative_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return str(iso)[:16] if iso else ""

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "ahora mismo"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 86400:
        return f"hace {seconds // 3600} h"
    if seconds < 2 * 86400:
        return "ayer"
    if seconds < 7 * 86400:
        return f"hace {seconds // 86400} d"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def elide_middle(text: str, max_len: int = 64) -> str:
    text = str(text)
    if len(text) <= max_len:
        return text
    keep = max_len - 1
    head = keep * 2 // 3
    return text[:head] + "…" + text[-(keep - head) :]


def abandon_busy_close(widget, worker, event, *, busy_text: str) -> None:
    """closeEvent helper: wait, or detach worker and close the window.

    Does not kill in-flight HTTP (up to provider timeout). The user gets
    the window back without ``kill`` from a terminal.
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(widget)
    box.setWindowTitle("FileWizard")
    box.setText(busy_text)
    box.setInformativeText(
        "«Salir de todos modos» cancela cuando sea posible y cierra esta "
        "ventana. Una llamada OCR/VLM puede seguir hasta su timeout."
    )
    wait_btn = box.addButton("Esperar", QMessageBox.ButtonRole.RejectRole)
    leave_btn = box.addButton(
        "Salir de todos modos", QMessageBox.ButtonRole.AcceptRole
    )
    box.setDefaultButton(wait_btn)
    box.exec()
    if box.clickedButton() is not leave_btn:
        event.ignore()
        return
    if worker is not None and hasattr(worker, "request_cancel"):
        worker.request_cancel()
    if worker is not None:
        try:
            worker.done.disconnect()
        except Exception:
            pass
        try:
            worker.setParent(None)
        except RuntimeError:
            pass
    event.accept()


STATUS_GLYPHS = {
    "done": "✓",
    "failed": "✕",
    "error": "✕",
    "skipped": "⏭",
    "pending": "…",
    "interrupted": "⚠",
    "undone": "↩",
    "dry-run": "◌",
    "manual": "✎",
}
