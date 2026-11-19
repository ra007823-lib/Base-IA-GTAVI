"""Fluxo manual: copiar o pedido, colar no chat do Claude e trazer a resposta de volta."""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout, QWidget

from ..security import ValidationError
from .widgets import button, label, open_url, row

CLAUDE_CHAT_URL = "https://claude.ai/new"


class PasteDialog(QDialog):
    """Mostra o pedido pronto e valida a resposta colada. O resultado fica em `result_value`."""

    def __init__(
        self, parent: QWidget | None, title: str, prompt: str,
        parse: Callable[[str], object],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 640)
        self.prompt = prompt
        self._parse = parse
        self.result_value: object | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(label(
            "1. Copie o pedido e cole no chat do Claude.   2. Copie a resposta dele e cole "
            "na caixa de baixo.   3. Clique em “Usar resposta”. Nada é enviado pelo app."
        ))
        self.prompt_box = QPlainTextEdit(prompt)
        self.prompt_box.setReadOnly(True)
        layout.addWidget(self.prompt_box, 2)
        layout.addLayout(row(
            button("Copiar pedido", self.copy_prompt, True),
            button("Abrir o chat do Claude", lambda: open_url(self, CLAUDE_CHAT_URL)),
        ))
        layout.addWidget(label("Resposta do Claude"))
        self.answer = QPlainTextEdit()
        self.answer.setPlaceholderText("Cole aqui a resposta (JSON)")
        layout.addWidget(self.answer, 2)
        self.error = label("", "Muted")
        layout.addWidget(self.error)
        layout.addLayout(row(button("Usar resposta", self.submit, True), button("Cancelar", self.reject)))

    def copy_prompt(self) -> None:
        QGuiApplication.clipboard().setText(self.prompt)
        self.error.setText("Pedido copiado.")

    def submit(self) -> bool:
        try:
            self.result_value = self._parse(self.answer.toPlainText())
        except ValidationError as exc:
            self.error.setText(str(exc))
            return False
        self.accept()
        return True
