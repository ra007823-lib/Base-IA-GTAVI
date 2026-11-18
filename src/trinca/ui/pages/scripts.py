"""Roteiros: texto de cada bloco e lista de gravação."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea,
    QVBoxLayout, QWidget,
)

from ...context import AppContext
from ...security import ValidationError, clean_text, video_url
from ..widgets import (
    Card, Page, button, chip, clear_layout, confirm, fmt_time, label, open_url, row,
    status_text, warn,
)

_EDITABLE = ("em_roteiro", "aguardando_gravacao")


class ScriptsPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Roteiros",
            "Revise o texto de cada bloco. A lista de gravação mostra a cena que você "
            "precisa reproduzir no jogo.",
        )
        self.ctx = ctx
        self._editors: list[tuple[int, QPlainTextEdit]] = []
        self._script_id: int | None = None

        columns = QHBoxLayout()
        columns.setSpacing(12)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentItemChanged.connect(lambda *_: self._load_current())
        columns.addWidget(self.list, 2)

        editor = Card()
        self.title = QLineEdit()
        self.title.setMaxLength(100)
        self.status_row = QHBoxLayout()
        editor.body.addWidget(self.title)
        editor.body.addLayout(self.status_row)
        body = QWidget()
        body.setObjectName("ScrollBody")
        body.setStyleSheet("QWidget#ScrollBody { background: transparent; }")
        self.blocks = QVBoxLayout(body)
        self.blocks.setContentsMargins(0, 0, 6, 0)
        self.blocks.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setWidget(body)
        editor.body.addWidget(scroll, 1)
        self.save_button = button("Salvar", self.save)
        self.send_button = button("Enviar para gravação", self.send_to_recording, True)
        editor.body.addLayout(
            row(self.save_button, self.send_button, button("Excluir roteiro", self.delete))
        )
        columns.addWidget(editor, 5)
        self.root.addLayout(columns, 1)

    def refresh(self) -> None:
        keep = self._script_id
        self.list.blockSignals(True)
        self.list.clear()
        for script in self.ctx.repo.list_scripts():
            item = QListWidgetItem(f"{script['title']}\n{status_text(script['status'])[0]}")
            item.setData(Qt.ItemDataRole.UserRole, script["id"])
            self.list.addItem(item)
            if script["id"] == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._load_current()

    def _load_current(self) -> None:
        item = self.list.currentItem()
        self._script_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._editors = []
        clear_layout(self.blocks)
        clear_layout(self.status_row)
        script = self.ctx.repo.get_script(self._script_id) if self._script_id else None
        editable = script is not None and script["status"] in _EDITABLE
        self.title.setEnabled(editable)
        self.save_button.setEnabled(editable)
        self.send_button.setEnabled(script is not None and script["status"] == "em_roteiro")
        if script is None:
            self.title.setText("")
            self.blocks.addWidget(label("Nenhum roteiro ainda. Gere um na tela Curiosidades.", "Muted"))
            self.blocks.addStretch(1)
            return
        self.title.setText(script["title"])
        self.status_row.addWidget(chip(script["status"]))
        self.status_row.addStretch(1)
        for block in self.ctx.repo.list_blocks(script["id"]):
            self.blocks.addWidget(label(f"Bloco {block['position']}", "H2"))
            text = QPlainTextEdit(block["text"])
            text.setFixedHeight(92)
            text.setReadOnly(not editable)
            self.blocks.addWidget(text)
            self._editors.append((block["id"], text))
            self.blocks.addWidget(label(f"Cena para gravar: {block['scene_hint']}", "Muted"))
            if block["video_youtube_id"]:
                url = video_url(block["video_youtube_id"], block["source_start_s"])
                moment = fmt_time(block["source_start_s"])
                self.blocks.addLayout(
                    row(button(f"Ver o momento original ({moment})",
                               lambda url=url: open_url(self, url)))
                )
        self.blocks.addStretch(1)

    def save(self) -> bool:
        if self._script_id is None:
            return False
        try:
            title = clean_text(self.title.text(), 100, required=True)
            texts = [
                (block_id, clean_text(editor.toPlainText(), 700, required=True))
                for block_id, editor in self._editors
            ]
        except ValidationError:
            warn(self, "O título e o texto de cada bloco não podem ficar vazios.")
            return False
        self.ctx.repo.update_script(self._script_id, title=title)
        for block_id, text in texts:
            self.ctx.repo.update_block(block_id, text=text, caption=text)
        self.ctx.message.emit("Roteiro salvo.")
        self.refresh()
        return True

    def send_to_recording(self) -> None:
        if self.save():
            self.ctx.repo.update_script(self._script_id, status="aguardando_gravacao")
            self.ctx.message.emit("Roteiro enviado para gravação. Importe o material na próxima tela.")
            self.refresh()

    def delete(self) -> None:
        if self._script_id is None:
            return
        if confirm(self, "Excluir o roteiro? As curiosidades dele voltam para o estado “nova”."):
            self.ctx.repo.delete_script(self._script_id)
            self._script_id = None
            self.refresh()
