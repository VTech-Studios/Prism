from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from ..domain.errors import PrismError
from .core import PrismCore, PrismState

_LOG = logging.getLogger(__name__)

Command = Callable[[PrismCore], None]


class RuntimeLoop:
    """Runs the core on its own thread, so slow USB writes never stall the window.

    The window never touches the core directly: it submits commands, which
    run between frames, and receives a fresh state whenever something changed.
    """

    def __init__(self, core: PrismCore) -> None:
        self._core = core
        self._listeners: list[Callable[[PrismState], None]] = []
        self._commands: queue.SimpleQueue[Command] = queue.SimpleQueue()
        self._running = threading.Event()
        self._thread = threading.Thread(target=self._run, name="prism-runtime", daemon=True)

    def subscribe(self, listener: Callable[[PrismState], None]) -> None:
        """Be told about every new state. Call before starting the loop.

        @param listener: called on the loop's thread with each new state.
        """
        self._listeners.append(listener)

    def start(self) -> None:
        """Start the loop, which connects to the devices first."""
        self._running.set()
        self._thread.start()

    def submit(self, command: Command) -> None:
        """Queue a command to run on the loop's thread.

        @param command: a function given the core.
        """
        self._commands.put(command)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop, which leaves the fans safe and releases the devices.

        @param timeout: seconds to wait for it to finish.
        """
        self._running.clear()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        """Connect, then run frames until stopped, then shut down."""
        self._guarded(PrismCore.start)
        while self._running.is_set():
            started = time.monotonic()
            self._drain()
            self._guarded(PrismCore.tick)
            if self._core.changed:
                state = self._core.state()
                for listener in self._listeners:
                    listener(state)
            period = 1.0 / self._core.settings.frame_rate
            time.sleep(max(0.0, period - (time.monotonic() - started)))
        self._guarded(PrismCore.shutdown)

    def _drain(self) -> None:
        """Run every queued command."""
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            self._guarded(command)

    def _guarded(self, command: Command) -> None:
        """Run one command, reporting refusals to the user and logging anything unexpected.

        One bad command must never stop the loop, because the loop is what keeps the fans right.

        @param command: the command.
        """
        try:
            command(self._core)
        except PrismError as error:
            self._core.notify(str(error))
        except Exception:
            _LOG.exception("unexpected failure in the runtime loop")
            self._core.notify("Something went wrong; see the log for details")
