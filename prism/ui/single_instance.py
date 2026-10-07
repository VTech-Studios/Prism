from __future__ import annotations

from collections.abc import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "prism-single-instance"


def already_running(name: str = SERVER_NAME) -> bool:
    """Ask a running Prism to show its window.

    Two copies would fight over the same USB devices, so a second launch
    only wakes the first.

    @param name: the local socket name.
    @return: True if another Prism answered and was asked to show itself.
    """
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


class InstanceServer(QLocalServer):
    """Listens for later launches and shows the window when one arrives."""

    def __init__(self, on_wake: Callable[[], None], name: str = SERVER_NAME) -> None:
        super().__init__()
        self._on_wake = on_wake
        QLocalServer.removeServer(name)
        self.listen(name)
        self.newConnection.connect(self._wake)

    def _wake(self) -> None:
        """Accept the knock and bring the window forward."""
        connection = self.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
        self._on_wake()
