"""Terminal progress output (stderr), shared by local and service commands."""

from typing import TextIO

from doctranslator_core.types import TranslationProgress

__all__ = ["ProgressPrinter"]


class ProgressPrinter:
    """Prints progress: one rewritten line on a terminal, otherwise one line per step."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._interactive = stream.isatty()
        self._last = ""
        self._open_line = False

    def __call__(self, progress: TranslationProgress) -> None:
        text = f"{progress.phase.value} {progress.done}/{progress.total}"
        if text == self._last:
            return
        self._last = text
        if self._interactive:
            self._stream.write(f"\r{text:<40}")
            self._open_line = True
        else:
            self._stream.write(text + "\n")
        self._stream.flush()

    def finish(self) -> None:
        if self._open_line:
            self._stream.write("\n")
            self._stream.flush()
            self._open_line = False
