from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    progress = Signal(object, object)


class FunctionWorker(QRunnable):
    def __init__(
        self,
        function: Callable[..., object],
        *,
        with_progress: bool = False,
    ):
        super().__init__()
        self.function = function
        self.with_progress = with_progress
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        result = (
            self.function(self.signals.progress.emit)
            if self.with_progress
            else self.function()
        )
        self.signals.finished.emit(result)
