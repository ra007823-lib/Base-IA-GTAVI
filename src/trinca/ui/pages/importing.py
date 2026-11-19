"""Importação e narração: material próprio de cada bloco e a voz do vídeo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QFileDialog, QInputDialog, QRadioButton, QVBoxLayout

from ...context import AppContext
from ...pipeline.assembly import DEMO_MEDIA
from ...config import CUT_BUFFER_S, MAX_OUTPUT_S, MIN_OUTPUT_S
from ...pipeline.media import cut_range, probe_duration, script_dir
from ...security import (
    AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, ValidationError, clean_text, safe_media_path,
)
from ..widgets import Card, Page, button, clear_layout, label, row, warn


def _media_name(path: str) -> str:
    if not path:
        return "Nenhum arquivo"
    return "Material de demonstração" if path == DEMO_MEDIA else Path(path).name


def _mode(script) -> str:
    return "original" if script["original_audio"] else script["narration_mode"]


def _pattern(extensions: frozenset[str]) -> str:
    return " ".join(f"*{ext}" for ext in sorted(extensions))


class ImportPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Importação e narração",
            "As imagens e o áudio do vídeo final vêm apenas dos arquivos que você importa aqui.",
        )
        self.ctx = ctx
        self._script_id: int | None = None

        self.scripts = QComboBox()
        self.scripts.setMinimumWidth(420)
        self.scripts.currentIndexChanged.connect(lambda _: self._load_current())
        self.root.addLayout(row(label("Roteiro"), self.scripts))

        blocks = Card("Vídeo de cada bloco")
        self.blocks = QVBoxLayout()
        self.blocks.setSpacing(8)
        blocks.body.addLayout(self.blocks)
        self.root.addWidget(blocks)

        narration = Card("Narração")
        self.own = QRadioButton("Minha gravação de voz")
        self.synthetic = QRadioButton("Voz sintética (terceira IA)")
        self.original = QRadioButton("Áudio original do vídeo (corte, sem narração)")
        for radio in (self.own, self.synthetic, self.original):
            radio.toggled.connect(self._mode_changed)
        self.narration_label = label("", "Muted")
        self.narration_button = button("Importar narração…", self.import_narration)
        narration.body.addWidget(self.own)
        narration.body.addLayout(row(self.narration_button, self.narration_label))
        narration.body.addWidget(self.synthetic)
        narration.body.addWidget(self.original)
        self.root.addWidget(narration)
        self.root.addStretch(1)

        self.demo_button = button("Usar material de demonstração", self.fill_demo)
        self.demo_button.setVisible(ctx.demo)
        self.prepare_button = button("Transcrever, sincronizar e gerar legendas", self.prepare, True)
        self.root.addLayout(row(self.demo_button, self.prepare_button))

    def refresh(self) -> None:
        keep = self._script_id
        self.scripts.blockSignals(True)
        self.scripts.clear()
        for script in self.ctx.repo.list_scripts(("aguardando_gravacao", "gravado")):
            self.scripts.addItem(script["title"], script["id"])
        index = self.scripts.findData(keep)
        if index >= 0:
            self.scripts.setCurrentIndex(index)
        self.scripts.blockSignals(False)
        self._load_current()

    def _load_current(self) -> None:
        self._script_id = self.scripts.currentData()
        clear_layout(self.blocks)
        script = self.ctx.repo.get_script(self._script_id) if self._script_id else None
        for widget in (self.own, self.synthetic, self.original, self.narration_button, self.demo_button,
                       self.prepare_button):
            widget.setEnabled(script is not None)
        if script is None:
            self.blocks.addWidget(
                label("Nenhum roteiro aguardando gravação. Envie um pela tela Roteiros.", "Muted")
            )
            self.narration_label.setText("")
            return
        for block in self.ctx.repo.list_blocks(script["id"]):
            block_id = block["id"]
            self.blocks.addLayout(
                row(
                    label(f"Bloco {block['position']}"),
                    button("Importar vídeo…", lambda block_id=block_id: self.import_video(block_id)),
                    *self._download_widgets(block),
                    label(_media_name(block["media_path"]), "Muted"),
                    label(block["scene_hint"], "Muted"),
                )
            )
        mode_now = _mode(script)
        for radio, mode in ((self.own, "propria"), (self.synthetic, "sintetica"),
                            (self.original, "original")):
            radio.blockSignals(True)
            radio.setChecked(mode_now == mode)
            radio.blockSignals(False)
        self.narration_button.setEnabled(mode_now == "propria")
        self.narration_label.setText(_media_name(script["narration_path"]))

    def _download_widgets(self, block) -> list:
        if not block["video_youtube_id"]:
            return []
        block_id = block["id"]
        return [button("Baixar vídeo completo", lambda block_id=block_id: self.download_source(block_id))]

    def _ensure_permission(self, block) -> bool:
        """O trecho só é baixado se o canal autorizou o uso, e a prova fica registrada."""
        if block["channel_permission"] == "autorizado":
            return True
        proof, ok = QInputDialog.getText(
            self, "Autorização do canal",
            f"Baixar um trecho do canal “{block['channel_name']}” só é permitido com a "
            "autorização dele. Se você tem, diga onde ela está registrada (e-mail, link, "
            "contrato). Isso fica salvo no app.",
        )
        if not ok:
            return False
        try:
            self.ctx.repo.set_channel_permission(block["channel_id"], proof)
        except ValidationError as exc:
            warn(self, str(exc))
            return False
        return True

    def download_source(self, block_id: int) -> None:
        if self._script_id is None:
            return
        repo = self.ctx.repo
        script = repo.get_script(self._script_id)
        block = next((b for b in repo.list_blocks(self._script_id) if b["id"] == block_id), None)
        if block is None or not block["video_youtube_id"]:
            return
        if not self._ensure_permission(block):
            return
        try:
            folder = script_dir(self.ctx.output_dir(), script["id"], script["title"]).parent
            dest = folder / "fontes" / f"{block['video_youtube_id']}.mp4"
        except (ValidationError, OSError) as exc:
            warn(self, f"Não foi possível preparar a pasta de saída: {exc}")
            return
        downloader = self.ctx.services.downloader
        video_id, start, end = block["video_youtube_id"], block["source_start_s"], block["source_end_s"]

        def work(progress, cancelled):
            path = downloader.fetch(video_id, dest, progress, cancelled)
            total = probe_duration(Path(path)) if path != DEMO_MEDIA else 0.0
            return path, total

        def done(result) -> str:
            path, total = result
            fields = {"media_path": clean_text(path, 1024)}
            if total > 0:
                cut_start, cut_end = cut_range(
                    start - CUT_BUFFER_S, end + CUT_BUFFER_S, total, MIN_OUTPUT_S, MAX_OUTPUT_S
                )
                fields.update(duration_s=total, trim_start=cut_start, trim_end=cut_end)
            repo.update_block(block_id, **fields)
            self._mark_recorded()
            self._load_current()
            if total > 0:
                return (f"Vídeo baixado. Corte inicial: {fields['trim_start']:.0f}s a "
                        f"{fields['trim_end']:.0f}s. Ajuste na Revisão.")
            return "Vídeo baixado e ligado ao bloco."

        self.ctx.run_task("Download do vídeo", work, done)

    def _mode_changed(self, checked: bool) -> None:
        if self._script_id is None or not checked:
            return
        if self.original.isChecked():
            self.ctx.repo.update_script(self._script_id, original_audio=1)
        else:
            mode = "propria" if self.own.isChecked() else "sintetica"
            self.ctx.repo.update_script(self._script_id, original_audio=0, narration_mode=mode)
        self._load_current()

    def _pick(self, title: str, extensions: frozenset[str]) -> str | None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, title, str(Path.home()), f"Arquivos aceitos ({_pattern(extensions)})"
        )
        if not chosen:
            return None
        try:
            return str(safe_media_path(chosen, extensions))
        except ValidationError as exc:
            warn(self, str(exc))
            return None

    def import_video(self, block_id: int) -> None:
        path = self._pick("Escolher o vídeo do bloco", VIDEO_EXTENSIONS)
        if path:
            self.ctx.repo.update_block(block_id, media_path=path)
            self._mark_recorded()
            self._load_current()

    def import_narration(self) -> None:
        if self._script_id is None:
            return
        path = self._pick("Escolher a narração", AUDIO_EXTENSIONS)
        if path:
            self.ctx.repo.update_script(self._script_id, narration_path=path)
            self._load_current()

    def fill_demo(self) -> None:
        if self._script_id is None:
            return
        repo = self.ctx.repo
        for block in repo.list_blocks(self._script_id):
            if not block["media_path"]:
                repo.update_block(block["id"], media_path=DEMO_MEDIA)
        if not repo.get_script(self._script_id)["narration_path"]:
            repo.update_script(self._script_id, narration_path=DEMO_MEDIA)
        self._mark_recorded()
        self._load_current()

    def _mark_recorded(self) -> None:
        repo = self.ctx.repo
        if all(block["media_path"] for block in repo.list_blocks(self._script_id)):
            repo.update_script(self._script_id, status="gravado")

    def prepare(self) -> None:
        if self._script_id is None:
            return
        repo = self.ctx.repo
        script_id = self._script_id
        script = repo.get_script(script_id)
        blocks = repo.list_blocks(script_id)
        if not all(block["media_path"] for block in blocks):
            warn(self, "Importe o vídeo de todos os blocos antes de continuar.")
            return
        if script["original_audio"]:
            # Corte do vídeo real: sem narração nem legenda; os cortes já estão nos blocos.
            repo.update_script(script_id, status="aguardando_revisao", render_path="")
            self.refresh()
            self.ctx.navigate.emit("revisao")
            self.ctx.message.emit("Cortes prontos. Ajuste início e fim na Revisão.")
            return
        if script["narration_mode"] == "propria" and not script["narration_path"]:
            warn(self, "Importe a sua narração ou escolha a voz sintética.")
            return
        speech = self.ctx.services.speech
        texts = [(block["id"], block["text"]) for block in blocks]
        mode = script["narration_mode"]

        narration_path = script["narration_path"]
        try:
            work_dir = script_dir(self.ctx.output_dir(), script_id, script["title"])
        except (ValidationError, OSError) as exc:
            warn(self, f"Não foi possível preparar a pasta de saída: {exc}")
            return

        def work(progress, cancelled):
            return speech.prepare(
                texts, mode, progress, cancelled, narration_path=narration_path, work_dir=work_dir
            )

        def done(timings) -> str:
            known = {block_id for block_id, _ in texts}
            repo.add_usage("speech")
            for timing in timings:
                if timing.block_id not in known or not 0 < timing.duration_s <= 600:
                    raise ValidationError("A sincronização devolveu dados fora do esperado.")
                repo.update_block(
                    timing.block_id, duration_s=timing.duration_s, trim_start=0,
                    trim_end=timing.duration_s, caption=clean_text(timing.caption, 700),
                )
            repo.update_script(script_id, status="aguardando_revisao", render_path="")
            self.refresh()
            self.ctx.navigate.emit("revisao")
            return "Legendas prontas. O vídeo aguarda a sua revisão."

        self.ctx.run_task("Narração e legendas", work, done)
