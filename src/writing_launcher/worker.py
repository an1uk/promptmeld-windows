from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], object]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.finished.emit(self.function())
