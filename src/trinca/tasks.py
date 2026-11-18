"""Tarefas em segundo plano, com progresso e cancelamento.

O processamento longo nunca roda na thread da interface. A função da tarefa
só calcula e devolve o resultado; a gravação no banco acontece depois, na
thread principal.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from .credentials import CredentialError
from .pipeline.contracts import Cancelled, IsCancelled, Progress, ServiceError
from .security import ValidationError, redact

log = logging.getLogger(__name__)

TaskFn = Callable[[Progress, IsCancelled], object]


class TaskSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class Task(QRunnable):
    def __init__(self, fn: TaskFn) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.signals = TaskSignals()
        self._fn = fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = self._fn(self.signals.progress.emit, self._cancel.is_set)
        except Cancelled:
            self.signals.cancelled.emit()
        except (ValidationError, CredentialError, ServiceError) as exc:
            self.signals.failed.emit(redact(str(exc)))
        except Exception as exc:  # noqa: BLE001 - a interface precisa saber de qualquer falha
            log.exception("Falha em tarefa de segundo plano")
            self.signals.failed.emit(redact(f"Erro inesperado: {exc}"))
        else:
            if self._cancel.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(result)
