"""Configurações: chaves de API, terceira IA, pastas e padrões do vídeo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from ...config import CAPTION_STYLES, CLAUDE_MODELS, GEMINI_MODELS, SPEECH_PROVIDERS
from ...context import AppContext
from ...credentials import SERVICES, CredentialError
from ...security import ValidationError
from ..widgets import Card, Page, button, confirm, label, row, warn

REAL_MODE_KEYS = ("gemini", "claude")


class SettingsPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Configurações",
            "As chaves ficam no cofre do sistema operacional. Elas nunca são gravadas em "
            "arquivo nem aparecem em logs.",
        )
        self.ctx = ctx
        repo = ctx.repo

        # O conteúdo rola quando a janela é baixa demais para todos os cartões.
        body = QWidget()
        body.setObjectName("ScrollBody")
        body.setStyleSheet("QWidget#ScrollBody { background: transparent; }")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 8, 0)
        content.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

        keys = Card("Chaves de API")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.key_status = {}
        self.key_inputs = {}
        for line, (name, title) in enumerate(SERVICES.items()):
            status = label("", "Muted")
            entry = QLineEdit()
            entry.setEchoMode(QLineEdit.EchoMode.Password)
            entry.setPlaceholderText("Cole a chave aqui")
            entry.setMaxLength(512)
            self.key_status[name] = status
            self.key_inputs[name] = entry
            grid.addWidget(label(title), line, 0)
            grid.addWidget(status, line, 1)
            grid.addWidget(entry, line, 2)
            grid.addWidget(button("Salvar", lambda name=name: self.save_key(name)), line, 3)
            grid.addWidget(button("Remover", lambda name=name: self.remove_key(name)), line, 4)
        grid.setColumnStretch(2, 1)
        keys.body.addLayout(grid)
        content.addWidget(keys)

        mode = Card("Modo de operação")
        self.mode_label = label("")
        self.mode_button = button("", self.toggle_mode)
        mode.body.addWidget(self.mode_label)
        mode.body.addLayout(row(self.mode_button))
        content.addWidget(mode)

        lower = QHBoxLayout()
        lower.setSpacing(12)

        video = Card("Padrões do vídeo e terceira IA")
        form = QFormLayout()
        self.max_duration = QSpinBox()
        self.max_duration.setRange(15, 180)
        self.max_duration.setSuffix(" s")
        self.max_duration.setValue(int(repo.get_setting("max_duration_s")))
        self.max_duration.valueChanged.connect(
            lambda value: repo.set_setting("max_duration_s", str(value))
        )
        self.caption_style = QComboBox()
        self.caption_style.addItems(CAPTION_STYLES)
        self.caption_style.setCurrentText(repo.get_setting("caption_style"))
        self.caption_style.currentTextChanged.connect(
            lambda value: repo.set_setting("caption_style", value)
        )
        self.provider = QComboBox()
        for key, title in SPEECH_PROVIDERS.items():
            self.provider.addItem(title, key)
        self.provider.setCurrentIndex(max(self.provider.findData(repo.get_setting("speech_provider")), 0))
        self.provider.currentIndexChanged.connect(
            lambda _: repo.set_setting("speech_provider", self.provider.currentData())
        )
        form.addRow("Duração máxima", self.max_duration)
        form.addRow("Estilo das legendas", self.caption_style)
        form.addRow("Provedor da terceira IA", self.provider)
        self.model_inputs = {}
        self.writer = QComboBox()
        if not ctx.demo:
            self.writer.addItem("Gemini (mesma chave da análise)", "gemini")
            self.writer.addItem("Claude (chave da API)", "claude")
            self.writer.setCurrentIndex(max(self.writer.findData(ctx.models["writer"]), 0))
            self.writer.currentIndexChanged.connect(
                lambda _: ctx.set_writer(self.writer.currentData())
            )
            form.addRow("Quem escreve os roteiros", self.writer)
            for kind, title, options in (
                ("gemini", "Modelo do Gemini", GEMINI_MODELS),
                ("claude", "Modelo do Claude", CLAUDE_MODELS),
            ):
                combo = QComboBox()
                combo.setEditable(True)
                combo.addItems(options)
                combo.setCurrentText(ctx.models[kind])
                combo.activated.connect(lambda _, kind=kind: self.save_model(kind))
                combo.lineEdit().editingFinished.connect(lambda kind=kind: self.save_model(kind))
                self.model_inputs[kind] = combo
                form.addRow(title, combo)
        video.body.addLayout(form)
        video.body.addStretch(1)
        lower.addWidget(video, 1)

        folders = Card("Pasta de saída")
        self.output_label = label("")
        folders.body.addWidget(label("Os pacotes de publicação e os vídeos finais ficam aqui.", "Muted"))
        folders.body.addWidget(self.output_label)
        folders.body.addLayout(
            row(button("Escolher pasta…", self.choose_output),
                button("Usar a pasta padrão", self.reset_output))
        )
        folders.body.addStretch(1)
        lower.addWidget(folders, 1)
        content.addLayout(lower)
        content.addStretch(1)

    def refresh(self) -> None:
        missing = []
        for name, status in self.key_status.items():
            text = self.ctx.credentials.masked(name)
            status.setText(text)
            if name == "claude" and self.ctx.models.get("writer") != "claude":
                continue  # a chave do Claude só é necessária quando ele é o roteirista
            if name in REAL_MODE_KEYS and not text.startswith("Salva"):
                missing.append(SERVICES[name])
        self.output_label.setText(str(self.ctx.output_dir()))
        if self.ctx.demo:
            self.mode_label.setText(
                "Demonstração: dados fictícios, nenhuma API é chamada e as chaves não são usadas."
            )
            self.mode_button.setText("Usar o modo real")
        else:
            text = (
                "Real: o radar lê o YouTube sem chave (yt-dlp), a análise usa o Gemini, os roteiros "
                "usam o Gemini ou o Claude (à sua escolha; o botão “colar” usa o chat do Claude "
                "sem chave), a voz usa o edge-tts e o Whisper, e a montagem usa o FFmpeg."
            )
            if self.ctx.services.simulated:
                text += " Ainda são simulados: " + ", ".join(self.ctx.services.simulated) + "."
            if missing:
                text += " Faltam as chaves de: " + ", ".join(missing) + "."
            self.mode_label.setText(text)
            self.mode_button.setText("Voltar à demonstração")

    def toggle_mode(self) -> None:
        if self.ctx.busy:
            warn(self, "Aguarde a tarefa atual terminar antes de trocar de modo.")
            return
        if self.ctx.demo and not confirm(
            self,
            "No modo real o app chama as APIs com as suas chaves, o que consome cota e "
            "pode gerar custos na sua conta de cada serviço. Continuar?",
        ):
            return
        self.ctx.switch_mode.emit(not self.ctx.demo)

    def save_model(self, kind: str) -> None:
        combo = self.model_inputs[kind]
        name = combo.currentText().strip()
        if name == self.ctx.models[kind]:
            return
        try:
            self.ctx.set_model(kind, name)
        except ValidationError as exc:
            combo.setCurrentText(self.ctx.models[kind])
            warn(self, str(exc))
            return
        self.ctx.message.emit(f"Modelo atualizado: {name}")

    def save_key(self, name: str) -> None:
        entry = self.key_inputs[name]
        try:
            self.ctx.credentials.set(name, entry.text())
        except CredentialError as exc:
            warn(self, str(exc))
            return
        finally:
            entry.clear()  # a chave não fica na tela nem na memória do campo
        self.ctx.message.emit(f"Chave de {SERVICES[name]} guardada no cofre do sistema.")
        self.refresh()

    def remove_key(self, name: str) -> None:
        if not confirm(self, f"Remover a chave de {SERVICES[name]} do cofre?"):
            return
        try:
            self.ctx.credentials.delete(name)
        except CredentialError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def choose_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Escolher a pasta de saída", str(Path.home()))
        if chosen:
            self.ctx.repo.set_setting("output_dir", str(Path(chosen).resolve()))
            self.refresh()

    def reset_output(self) -> None:
        self.ctx.repo.set_setting("output_dir", "")
        self.refresh()
