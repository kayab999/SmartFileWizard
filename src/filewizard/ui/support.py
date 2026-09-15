"""Public support / project URLs (no Qt)."""

from __future__ import annotations

SUPPORT_URL = "https://buymeacoffee.com/kayabsoftware"
REPO_URL = "https://github.com/kayab999/SmartFileWizard"


def open_support_links(parent=None) -> None:
    """Show the support dialog and open URLs the user picks."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

    dialog = QDialog(parent)
    dialog.setWindowTitle("Apoyar FileWizard")
    dialog.setModal(True)
    dialog.resize(480, 200)
    layout = QVBoxLayout(dialog)
    intro = QLabel(
        "FileWizard es un proyecto independiente. Si te resulta útil, "
        "puedes invitar a un café o seguir el código e issues en GitHub."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    row = QHBoxLayout()
    coffee = QPushButton("Invítame un café")
    coffee.setObjectName("btnPrimary")
    coffee.setAccessibleName("Invítame un café")
    coffee.setToolTip(SUPPORT_URL)
    coffee.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL))
    )
    github = QPushButton("GitHub")
    github.setAccessibleName("Abrir GitHub")
    github.setToolTip(REPO_URL)
    github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
    close_btn = QPushButton("Cerrar")
    close_btn.clicked.connect(dialog.accept)
    row.addWidget(coffee)
    row.addWidget(github)
    row.addWidget(close_btn)
    layout.addLayout(row)
    dialog.exec()
