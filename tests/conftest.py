from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class MemoryKeyring:
    """Cofre em memória para os testes. Não toca no cofre do sistema."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, name: str, value: str) -> None:
        self.data[(service, name)] = value

    def get_password(self, service: str, name: str) -> str | None:
        return self.data.get((service, name))

    def delete_password(self, service: str, name: str) -> None:
        self.data.pop((service, name), None)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    from trinca.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def ctx(qapp, tmp_path, monkeypatch):
    from trinca.context import build_context
    from trinca.credentials import CredentialStore

    monkeypatch.setenv("TRINCA_DATA_DIR", str(tmp_path / "dados"))
    context = build_context(delay=0, credentials=CredentialStore(MemoryKeyring()))
    yield context
    context.repo.close()


@pytest.fixture
def dialogs(monkeypatch):
    """Substitui as caixas de diálogo e registra os avisos mostrados."""
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, text: shown.append(text)
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda parent, title, text: QMessageBox.StandardButton.Yes
    )
    return shown


def wait_task(qapp, context, timeout: float = 10.0) -> None:
    """Processa eventos até a tarefa em segundo plano terminar."""
    deadline = time.monotonic() + timeout
    while context.busy:
        qapp.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("A tarefa não terminou a tempo.")
        time.sleep(0.01)
    qapp.processEvents()
