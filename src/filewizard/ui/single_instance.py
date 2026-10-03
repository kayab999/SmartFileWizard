"""One GUI process. A second launch asks the first window to show itself."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SERVER_NAME = "filewizard-gui"


def claim_primary(name: str = SERVER_NAME):
    """Listen as the primary instance, or signal the one already running.

    Returns the ``QLocalServer`` for this process, or None when another
    instance accepted the wakeup. Requires a ``QApplication``.
    """
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(250):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(250)
        socket.disconnectFromServer()
        return None

    QLocalServer.removeServer(name)
    server = QLocalServer()
    if not server.listen(name):
        logger.warning(
            "Single-instance socket %s did not listen: %s",
            name,
            server.errorString(),
        )
    return server


def accept_show_requests(server, window) -> None:
    """Raise ``window`` when a later launch connects."""

    def _on_connection() -> None:
        conn = server.nextPendingConnection()
        window.show()
        window.raise_()
        window.activateWindow()
        if conn is not None:
            conn.disconnectFromServer()

    server.newConnection.connect(_on_connection)
