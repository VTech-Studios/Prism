from __future__ import annotations

import subprocess
from collections.abc import Sequence

from ..domain.errors import DeviceError


class SubprocessRunner:
    def run(self, args: Sequence[str], timeout: float = 5.0) -> str:
        """Run a command to completion.

        @param args: the program and its arguments, never passed through a shell.
        @param timeout: seconds before the command is abandoned.
        @return: the command's standard output.
        @raise DeviceError: if the command is missing, times out, or fails.
        """
        try:
            done = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise DeviceError(f"{args[0]} failed: {error}") from error
        return done.stdout
