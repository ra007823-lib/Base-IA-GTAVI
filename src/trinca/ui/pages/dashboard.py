"""Painel: estado do pipeline, últimos vídeos e uso das APIs."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QProgressBar

from ...config import GEMINI_FREE_DAILY_VIDEO_S, YOUTUBE_DAILY_QUOTA
from ...context import AppContext
from .. import theme
from ..widgets import Card, LogoWidget, Page, button, fill_table, fmt_date, label, make_table, row

_STATS = (
    ("videos_novos", "Vídeos detectados", theme.CYAN),
    ("curiosidades_novas", "Curiosidades novas", theme.PINK),
    ("aguardando_gravacao", "Roteiros aguardando gravação", theme.ORANGE),
    ("aguardando_revisao", "Vídeos aguardando revisão", theme.ORANGE),
    ("publicados", "Publicados", theme.OK),
)


class DashboardPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__("Painel", "Estado do pipeline, do radar até a publicação.")
        self.ctx = ctx

        banner = QHBoxLayout()
        banner.addWidget(LogoWidget(132))
        banner.addWidget(label("Macaco: do radar à publicação, no clima de Vice City.", "Muted"), 1)
        self.root.addLayout(banner)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.values = {}
        for key, title, color in _STATS:
            card = Card()
            value = label("0", "StatValue")
            value.setStyleSheet(f"color: {color};")
            card.body.addWidget(value)
            card.body.addWidget(label(title, "Muted"))
            self.values[key] = value
            stats.addWidget(card)
        self.root.addLayout(stats)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        videos = Card("Últimos vídeos detectados")
        self.videos = make_table(["Vídeo", "Canal", "Publicado", "Estado"])
        videos.body.addWidget(self.videos)
        middle.addWidget(videos, 5)

        usage = Card("Uso das APIs hoje")
        self.youtube_label = label("")
        self.youtube_bar = QProgressBar()
        self.youtube_bar.setRange(0, YOUTUBE_DAILY_QUOTA)
        self.youtube_bar.setTextVisible(False)
        self.gemini_label = label("")
        self.video_label = label("", "Muted")
        self.claude_label = label("")
        self.speech_label = label("")
        for widget in (self.youtube_label, self.youtube_bar, self.gemini_label,
                       self.video_label, self.claude_label, self.speech_label):
            usage.body.addWidget(widget)
        usage.body.addStretch(1)
        middle.addWidget(usage, 2)
        self.root.addLayout(middle, 1)

        self.root.addLayout(
            row(
                button("Ver curiosidades novas", lambda: ctx.navigate.emit("curiosidades"), True),
                button("Abrir revisão", lambda: ctx.navigate.emit("revisao")),
                button("Abrir radar", lambda: ctx.navigate.emit("radar")),
            )
        )

    def refresh(self) -> None:
        repo = self.ctx.repo
        for key, value in repo.pipeline_counts().items():
            self.values[key].setText(str(value))
        fill_table(
            self.videos,
            [
                (v["id"], (v["title"], v["channel_name"], fmt_date(v["published_at"]),
                           ("estado", v["status"])))
                for v in repo.list_videos(limit=8)
            ],
        )
        usage = repo.usage_today()
        youtube = usage.get("youtube", 0)
        self.youtube_label.setText(
            f"YouTube Data API: {youtube:,} de {YOUTUBE_DAILY_QUOTA:,} unidades".replace(",", ".")
        )
        self.youtube_bar.setValue(min(youtube, YOUTUBE_DAILY_QUOTA))
        self.gemini_label.setText(f"Pedidos ao Gemini (analista): {usage.get('gemini', 0)}")
        watched = usage.get("gemini_video_s", 0)
        self.video_label.setText(
            f"Vídeo analisado hoje: {watched // 3600} h {watched % 3600 // 60:02d} min de "
            f"{GEMINI_FREE_DAILY_VIDEO_S // 3600} h do plano gratuito"
        )
        self.claude_label.setText(f"Pedidos ao Claude (roteirista): {usage.get('claude', 0)}")
        self.speech_label.setText(f"Pedidos à terceira IA (voz e legendas): {usage.get('speech', 0)}")
