"""Montagem e revisão: linha do tempo, ajustes e aprovação do vídeo."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QListWidget, QPlainTextEdit, QVBoxLayout, QWidget,
)

from pathlib import Path

from ...config import MAX_OUTPUT_S, MIN_OUTPUT_S
from ...context import AppContext
from ...pipeline.contracts import RenderBlock, RenderJob
from ...security import ValidationError, clean_text
from .. import theme
from ..widgets import Card, Page, button, chip, clear_layout, confirm, fmt_time, label, row, warn

_LANE_COLORS = (theme.PINK, theme.CYAN, theme.ORANGE)


class Timeline(QWidget):
    """Três faixas: vídeo, narração e legendas. O bloco escolhido fica destacado."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(146)
        self._durations: list[float] = []
        self._selected = -1

    def set_data(self, durations: list[float], selected: int) -> None:
        self._durations = durations
        self._selected = selected
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - nome definido pelo Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        label_width, gap, lane_height = 78, 8, 30
        total = sum(self._durations)
        painter.setFont(QFont(self.font().family(), 9))
        for lane, name in enumerate(("Vídeo", "Narração", "Legendas")):
            top = 6 + lane * (lane_height + gap)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRectF(0, top, label_width, lane_height),
                             Qt.AlignmentFlag.AlignVCenter, name)
            track = QRectF(label_width, top, self.width() - label_width - 2, lane_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.INPUT))
            painter.drawRoundedRect(track, 6, 6)
            if total <= 0:
                continue
            x = track.left()
            for index, duration in enumerate(self._durations):
                width = track.width() * duration / total
                rect = QRectF(x + 1, top + (0 if lane == 0 else 7), width - 2,
                              lane_height - (0 if lane == 0 else 14))
                color = QColor(_LANE_COLORS[index % 3] if lane == 0 else theme.MUTED)
                color.setAlpha(255 if index == self._selected else (150 if lane == 0 else 90))
                painter.setBrush(color)
                painter.setPen(
                    QPen(QColor(theme.TEXT), 2) if index == self._selected and lane == 0
                    else Qt.PenStyle.NoPen
                )
                painter.drawRoundedRect(rect, 5, 5)
                if lane == 0 and width > 46:
                    painter.setPen(QColor(theme.BG))
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                                     f"{index + 1} · {duration:.1f}s")
                x += width
        painter.setPen(QColor(theme.MUTED))
        bottom = 6 + 3 * (lane_height + gap)
        painter.drawText(QRectF(label_width, bottom, 200, 16), Qt.AlignmentFlag.AlignLeft, "00:00")
        painter.drawText(QRectF(self.width() - 202, bottom, 200, 16),
                         Qt.AlignmentFlag.AlignRight, fmt_time(total))
        painter.end()


class Preview(QWidget):
    """Quadro vertical 9:16 com a legenda do bloco escolhido (prévia ilustrativa)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(198, 352)
        self._caption = ""

    def set_caption(self, caption: str) -> None:
        self._caption = caption
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - nome definido pelo Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor("#2B1A4A"))
        gradient.setColorAt(0.55, QColor("#7A2A63"))
        gradient.setColorAt(1.0, QColor("#C9643F"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, 14, 14)
        painter.setPen(QColor(theme.TEXT))
        font = QFont(self.font().family(), 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            rect.adjusted(14, rect.height() * 0.55, -14, -18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
            | Qt.TextFlag.TextWordWrap,
            self._caption,
        )
        painter.end()


class VideoPlayer(QWidget):
    """Player do vídeo renderizado (QtMultimedia), em quadro 9:16."""

    def __init__(self) -> None:
        super().__init__()
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._video = QVideoWidget()
        self._video.setFixedSize(198, 352)
        self._player.setVideoOutput(self._video)
        self._toggle = button("Reproduzir", self._play_pause)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._toggle)
        self._loaded = ""

    def load(self, path: str) -> None:
        if path != self._loaded:
            from PySide6.QtCore import QUrl

            self._player.setSource(QUrl.fromLocalFile(path))
            self._loaded = path

    def stop(self) -> None:
        self._player.stop()

    def _play_pause(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._toggle.setText("Reproduzir")
        else:
            self._player.play()
            self._toggle.setText("Pausar")


class ReviewPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Montagem e revisão",
            "Ajuste os cortes e as legendas. Nada é publicado sem a sua aprovação aqui.",
        )
        self.ctx = ctx
        self._script_id: int | None = None
        self._blocks: list = []

        self.scripts = QComboBox()
        self.scripts.setMinimumWidth(420)
        self.scripts.currentIndexChanged.connect(lambda _: self._load_current())
        self.status_row = QHBoxLayout()
        top = row(label("Vídeo"), self.scripts, stretch=False)
        top.addLayout(self.status_row)
        top.addStretch(1)
        self.root.addLayout(top)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        preview = Card("Prévia")
        self.preview = Preview()
        preview.body.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        self.preview_note = label("Prévia ilustrativa. Renderize para ver o vídeo de verdade.", "Muted")
        preview.body.addWidget(self.preview_note)
        self.player: VideoPlayer | None = None
        self.player_box = preview.body
        preview.body.addStretch(1)
        columns.addWidget(preview, 2)

        work = Card("Linha do tempo")
        self.duration_label = label("")
        work.body.addWidget(self.duration_label)
        self.timeline = Timeline()
        work.body.addWidget(self.timeline)
        lower = QHBoxLayout()
        lower.setSpacing(12)
        self.block_list = QListWidget()
        self.block_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.block_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.block_list.currentRowChanged.connect(lambda _: self._show_block())
        lower.addWidget(self.block_list, 2)
        adjust = QHBoxLayout()
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for spin in (self.start, self.end):
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setSuffix(" s")
            spin.setMinimumWidth(96)
        adjust.addWidget(label("Início"))
        adjust.addWidget(self.start)
        adjust.addWidget(label("Fim"))
        adjust.addWidget(self.end)
        adjust.addStretch(1)
        self.caption = QPlainTextEdit()
        self.caption.setPlaceholderText("Legenda do bloco")
        self.apply_button = button("Aplicar ajustes", self.apply_adjust)
        side = QVBoxLayout()
        side.addLayout(adjust)
        side.addWidget(self.caption, 1)
        side.addLayout(row(self.apply_button))
        lower.addLayout(side, 3)
        work.body.addLayout(lower, 1)
        columns.addWidget(work, 5)
        self.root.addLayout(columns, 1)

        self.render_button = button("Renderizar", self.render)
        self.approve_button = button("Aprovar", self.approve, True)
        self.reject_button = button("Rejeitar", self.reject)
        self.render_label = label("", "Muted")
        self.root.addLayout(
            row(self.render_button, self.approve_button, self.reject_button, self.render_label)
        )

    def refresh(self) -> None:
        keep = self._script_id
        self.scripts.blockSignals(True)
        self.scripts.clear()
        for script in self.ctx.repo.list_scripts(("aguardando_revisao", "aprovado", "rejeitado")):
            self.scripts.addItem(script["title"], script["id"])
        index = self.scripts.findData(keep)
        if index >= 0:
            self.scripts.setCurrentIndex(index)
        self.scripts.blockSignals(False)
        self._load_current()

    def _load_current(self) -> None:
        self._script_id = self.scripts.currentData()
        repo = self.ctx.repo
        script = repo.get_script(self._script_id) if self._script_id else None
        self._blocks = repo.list_blocks(self._script_id) if script else []
        clear_layout(self.status_row)
        for widget in (self.render_button, self.approve_button, self.reject_button,
                       self.apply_button, self.start, self.end, self.caption):
            widget.setEnabled(script is not None)
        keep_row = max(self.block_list.currentRow(), 0)
        self.block_list.blockSignals(True)
        self.block_list.clear()
        for block in self._blocks:
            self.block_list.addItem(f"Bloco {block['position']}: {block['caption']}")
        if self._blocks:
            self.block_list.setCurrentRow(min(keep_row, len(self._blocks) - 1))
        self.block_list.blockSignals(False)
        if script is None:
            self.duration_label.setText("Nenhum vídeo aguardando revisão.")
            self.render_label.setText("")
            self.timeline.set_data([], -1)
            self.preview.set_caption("")
            self.caption.setPlainText("")
            self._show_player("")
            return
        self.status_row.addWidget(chip(script["status"]))
        total = self._total()
        limit = min(int(repo.get_setting("max_duration_s")), MAX_OUTPUT_S)
        over = total > limit or total < MIN_OUTPUT_S
        self.duration_label.setText(
            f"Duração total: {total:.1f} s (permitido: {MIN_OUTPUT_S} a {limit} s)"
            + (" — fora do limite" if over else "")
        )
        self.duration_label.setStyleSheet(f"color: {theme.DANGER if over else theme.TEXT};")
        rendered = bool(script["render_path"])
        self.render_label.setText(
            "Vídeo renderizado." if rendered else "Renderize o vídeo antes de aprovar."
        )
        self.approve_button.setEnabled(rendered and script["status"] != "aprovado")
        self._show_player(script["render_path"])
        self._show_block()

    def _show_player(self, render_path: str) -> None:
        path = Path(render_path) if render_path else None
        real = path is not None and path.is_absolute() and path.is_file()
        if real and self.player is None:
            try:
                self.player = VideoPlayer()
                self.player_box.insertWidget(1, self.player, 0, Qt.AlignmentFlag.AlignHCenter)
            except Exception:  # noqa: BLE001 - sem QtMultimedia, fica a prévia ilustrativa
                self.player = None
                real = False
        if self.player is not None:
            self.player.setVisible(real)
            if real:
                self.player.load(str(path))
            else:
                self.player.stop()
        self.preview.setVisible(not real)
        self.preview_note.setVisible(not real)

    def _total(self) -> float:
        return sum(block["trim_end"] - block["trim_start"] for block in self._blocks)

    def _show_block(self) -> None:
        index = self.block_list.currentRow()
        durations = [block["trim_end"] - block["trim_start"] for block in self._blocks]
        self.timeline.set_data(durations, index)
        if not 0 <= index < len(self._blocks):
            return
        block = self._blocks[index]
        for spin, value in ((self.start, block["trim_start"]), (self.end, block["trim_end"])):
            spin.setRange(0, block["duration_s"])
            spin.setValue(value)
        self.caption.setPlainText(block["caption"])
        self.preview.set_caption(block["caption"])

    def apply_adjust(self) -> None:
        index = self.block_list.currentRow()
        if not 0 <= index < len(self._blocks):
            return
        block = self._blocks[index]
        start, end = self.start.value(), self.end.value()
        if end - start < 1:
            warn(self, "O bloco precisa ter pelo menos 1 segundo.")
            return
        script = repo_script = self.ctx.repo.get_script(self._script_id)
        try:
            caption = clean_text(
                self.caption.toPlainText(), 700, required=not repo_script["original_audio"]
            )
        except ValidationError:
            warn(self, "A legenda não pode ficar vazia.")
            return
        repo = self.ctx.repo
        repo.update_block(block["id"], trim_start=start, trim_end=end, caption=caption)
        # Qualquer ajuste invalida a renderização e a aprovação anteriores.
        repo.update_script(self._script_id, render_path="", status="aguardando_revisao")
        self.ctx.message.emit("Ajustes aplicados. Renderize de novo para aprovar.")
        self._load_current()

    def render(self) -> None:
        if self._script_id is None:
            return
        script_id = self._script_id
        assembler = self.ctx.services.assembler
        repo = self.ctx.repo
        script = repo.get_script(script_id)
        blocks, offset = [], 0.0
        for block in repo.list_blocks(script_id):
            blocks.append(RenderBlock(
                block["id"], block["media_path"], block["trim_start"], block["trim_end"],
                block["caption"], offset,
            ))
            offset += block["duration_s"]
        job = RenderJob(
            script_id, script["title"], tuple(blocks),
            "original" if script["original_audio"] else script["narration_mode"],
            script["narration_path"], repo.get_setting("caption_style"),
            str(self.ctx.output_dir()),
        )

        def work(progress, cancelled):
            return assembler.render(job, progress, cancelled)

        def done(render_path) -> str:
            self.ctx.repo.update_script(script_id, render_path=clean_text(render_path, 1024))
            self.refresh()
            return "Renderização concluída. Revise e aprove o vídeo."

        self.ctx.run_task("Renderização", work, done)

    def approve(self) -> None:
        repo = self.ctx.repo
        script = repo.get_script(self._script_id) if self._script_id else None
        if script is None or not script["render_path"]:
            warn(self, "Renderize o vídeo antes de aprovar.")
            return
        limit = min(int(repo.get_setting("max_duration_s")), MAX_OUTPUT_S)
        if self._total() > limit and not confirm(
            self, f"O vídeo passa do limite de {limit} s. Aprovar mesmo assim?"
        ):
            return
        if self._total() < MIN_OUTPUT_S and not confirm(
            self, f"O vídeo tem menos de {MIN_OUTPUT_S} s. Aprovar mesmo assim?"
        ):
            return
        repo.update_script(self._script_id, status="aprovado")
        self.ctx.message.emit("Vídeo aprovado. Prepare a publicação.")
        self.ctx.navigate.emit("publicacao")

    def reject(self) -> None:
        if self._script_id is not None:
            self.ctx.repo.update_script(self._script_id, status="rejeitado")
            self.ctx.message.emit("Vídeo rejeitado. Ajuste os blocos e renderize de novo.")
            self._load_current()
