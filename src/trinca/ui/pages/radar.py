"""Radar: busca de vídeos por tema livre, canais monitorados e vídeos encontrados."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLineEdit,
    QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from ...config import (
    GEMINI_FREE_DAILY_VIDEO_S, SEARCH_COST_UNITS, SEARCH_DURATIONS,
    SEARCH_ORDERS, SEARCH_PERIODS, YOUTUBE_DAILY_QUOTA,
)
from ...context import AppContext
from ...pipeline.contracts import ChannelRef, SearchOptions
from ...security import (
    ValidationError, clean_text, clean_theme, parse_channel_ref, parse_video_ref,
    validate_channel_id, validate_video_id, video_url,
)
from ..widgets import (
    Card, Page, button, confirm, fill_table, fmt_date, fmt_time, label, make_table, open_url,
    row, selected_id, warn,
)


class AddChannelDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar canal")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.reference = QLineEdit()
        self.reference.setMaxLength(200)
        self.reference.setPlaceholderText("@canal, link do canal ou ID (UC…)")
        form.addRow("Canal", self.reference)
        form.addRow(label("O nome e a lista de envios são buscados no YouTube. "
                          "A busca gasta 1 unidade da cota diária.", "Muted"))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class RadarPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Radar de temas e canais",
            "Busque vídeos sobre o tema que quiser ou acompanhe canais. Os vídeos são "
            "analisados pela URL, nunca são baixados, e cada um só vira publicação uma vez.",
        )
        self.ctx = ctx

        sources = QTabWidget()
        sources.addTab(self._build_themes_tab(), "Busca por tema")
        sources.addTab(self._build_channels_tab(), "Canais monitorados")
        self.root.addWidget(sources, 4)

        feed = Card("Vídeos encontrados")
        self.videos = make_table(["Vídeo", "Canal", "Tema", "Publicado", "Duração", "Estado"])
        feed.body.addWidget(self.videos)
        feed.body.addLayout(
            row(
                button("Analisar com o Gemini", self.analyze_selected, True),
                button("Abrir no YouTube", self.open_selected),
                button("Adicionar vídeo por link…", self.add_video_by_link),
            )
        )
        self.root.addWidget(feed, 5)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._automatic_check)
        self._interval_changed(self.interval.value())

    def _combo(self, options, setting: str) -> QComboBox:
        """Lista de opções de busca, gravada nas configurações quando muda."""
        combo = QComboBox()
        for text, value in options:
            combo.addItem(text, value)
        index = combo.findData(type(options[0][1])(self.ctx.repo.get_setting(setting)))
        combo.setCurrentIndex(max(index, 0))
        combo.currentIndexChanged.connect(
            lambda _: self.ctx.repo.set_setting(setting, str(combo.currentData()))
        )
        return combo

    def _build_themes_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(18)

        search = QVBoxLayout()
        form = QFormLayout()
        self.theme_input = QLineEdit()
        self.theme_input.setMaxLength(80)
        self.theme_input.setPlaceholderText("Ex.: segredos do mapa de GTA VI")
        self.theme_input.returnPressed.connect(self.search_theme)
        self.order = self._combo(SEARCH_ORDERS, "search_order")
        self.period = self._combo(SEARCH_PERIODS, "search_period_days")
        self.duration = self._combo(SEARCH_DURATIONS, "search_duration")
        form.addRow("Tema", self.theme_input)
        form.addRow("Ordenar por", self.order)
        form.addRow("Publicados", self.period)
        form.addRow("Duração", self.duration)
        search.addLayout(form)
        search.addLayout(
            row(
                button("Buscar vídeos", self.search_theme, True),
                label(f"Cada busca gasta {SEARCH_COST_UNITS + 1} unidades da cota diária "
                      "do YouTube.", "Muted"),
            )
        )
        search.addStretch(1)
        layout.addLayout(search, 3)

        saved = QVBoxLayout()
        self.themes = make_table(["Temas já buscados", "Última busca"])
        self.themes.itemSelectionChanged.connect(self._theme_selected)
        saved.addWidget(self.themes)
        saved.addLayout(row(button("Remover tema", self.remove_theme)))
        layout.addLayout(saved, 2)
        return tab

    def _build_channels_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 14, 16, 14)
        self.channels = make_table(["Canal", "Uso permitido", "Estado"])
        layout.addWidget(self.channels)
        self.interval = QSpinBox()
        self.interval.setRange(5, 240)
        self.interval.setSuffix(" min")
        self.interval.setValue(int(self.ctx.repo.get_setting("radar_interval_min")))
        self.interval.valueChanged.connect(self._interval_changed)
        actions = row(
            button("Adicionar", self.add_channel),
            button("Pausar ou retomar", self.toggle_pause),
            button("Remover", self.remove_channel),
            button("Verificar agora", self.check_now),
            label("Verificar sozinho a cada"),
            self.interval,
        )
        layout.addLayout(actions)
        return tab

    def refresh(self) -> None:
        repo = self.ctx.repo
        fill_table(
            self.themes,
            [(t["id"], (t["query"], fmt_date(t["last_searched_at"]))) for t in repo.list_themes()],
        )
        fill_table(
            self.channels,
            [
                (c["id"], (c["name"], ("estado", c["permission"]),
                           ("estado", "pausado" if c["paused"] else "ativo")))
                for c in repo.list_channels()
            ],
        )
        fill_table(
            self.videos,
            [
                (v["id"], (v["title"], v["channel_name"], v["theme"] or "—",
                           fmt_date(v["published_at"]),
                           fmt_time(v["duration_s"]) if v["duration_s"] else "—",
                           ("estado", "usado" if v["used"] else v["status"])))
                for v in repo.list_videos()
            ],
        )

    def _quota_allows(self, units: int) -> bool:
        """Falso quando o gasto passaria da cota diária da YouTube Data API."""
        used = self.ctx.repo.usage_today().get("youtube", 0)
        return used + units <= YOUTUBE_DAILY_QUOTA

    # ----- temas -----

    def _theme_selected(self) -> None:
        theme_id = selected_id(self.themes)
        for theme in self.ctx.repo.list_themes():
            if theme["id"] == theme_id:
                self.theme_input.setText(theme["query"])

    def remove_theme(self) -> None:
        theme_id = selected_id(self.themes)
        if theme_id is None:
            warn(self, "Escolha um tema na lista.")
            return
        self.ctx.repo.remove_theme(theme_id)
        self.refresh()

    def search_theme(self) -> None:
        repo = self.ctx.repo
        try:
            theme = clean_theme(self.theme_input.text())
        except ValidationError as exc:
            warn(self, str(exc))
            return
        if not self._quota_allows(SEARCH_COST_UNITS + 1):
            warn(self, "A cota diária da YouTube Data API não comporta outra busca. "
                       "A busca por tema volta a funcionar amanhã.")
            return
        options = SearchOptions(
            self.order.currentData(), self.period.currentData(), self.duration.currentData()
        )
        known = repo.all_video_ids()
        radar = self.ctx.services.radar

        def work(progress, cancelled):
            return radar.search(theme, options, known, progress, cancelled)

        def done(result) -> str:
            repo.add_usage("youtube", result.units)
            repo.save_theme(theme)
            new = 0
            for video in result.videos:
                channel_id = repo.ensure_channel(
                    validate_channel_id(video.channel_youtube_id),
                    clean_text(video.channel_name, 80, required=True),
                )
                added = repo.add_video(
                    channel_id,
                    validate_video_id(video.youtube_id),
                    clean_text(video.title, 200, required=True),
                    clean_text(video.published_at, 32, required=True),
                    max(int(video.duration_s), 0),
                    theme,
                )
                new += added is not None
            self.refresh()
            return f"Busca por “{theme}”: {new} vídeo(s) novo(s)."

        self.ctx.run_task("Busca por tema", work, done)

    def add_video_by_link(self) -> None:
        """Acrescenta à lista um vídeo (por exemplo, do seu canal) a partir do link."""
        text, ok = QInputDialog.getText(
            self, "Adicionar vídeo por link",
            "Cole o link do vídeo do YouTube (ou o ID de 11 caracteres):",
        )
        if not ok:
            return
        try:
            video_id = parse_video_ref(text)
        except ValidationError as exc:
            warn(self, str(exc))
            return
        repo = self.ctx.repo
        if video_id in repo.all_video_ids():
            warn(self, "Este vídeo já está na lista ou já foi usado em uma publicação.")
            return
        radar = self.ctx.services.radar

        def work(progress, cancelled):
            return radar.fetch_video(video_id, progress, cancelled)

        def done(video) -> str:
            channel_id = repo.ensure_channel(
                validate_channel_id(video.channel_youtube_id),
                clean_text(video.channel_name, 80, required=True),
            )
            added = repo.add_video(
                channel_id, validate_video_id(video.youtube_id),
                clean_text(video.title, 200, required=True),
                clean_text(video.published_at, 32, required=True),
                max(int(video.duration_s), 0), "",
            )
            self.refresh()
            return "Vídeo adicionado à lista." if added else "Este vídeo já estava na lista."

        self.ctx.run_task("Vídeo por link", work, done)

    # ----- canais -----

    def add_channel(self) -> None:
        dialog = AddChannelDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.resolve_channel(dialog.reference.text())

    def resolve_channel(self, reference: str) -> None:
        """Busca o canal em segundo plano e o acrescenta à lista."""
        try:
            parse_channel_ref(reference)
        except ValidationError as exc:
            warn(self, str(exc))
            return
        radar = self.ctx.services.radar
        repo = self.ctx.repo

        def work(progress, cancelled):
            return radar.resolve(reference, progress, cancelled)

        def done(result) -> str:
            info, units = result
            repo.add_usage("youtube", units)
            repo.add_channel(
                validate_channel_id(info.youtube_id),
                clean_text(info.name, 80, required=True),
                info.uploads_playlist,
            )
            self.refresh()
            return f"Canal adicionado: {info.name}"

        self.ctx.run_task("Busca do canal", work, done)

    def toggle_pause(self) -> None:
        channel_id = selected_id(self.channels)
        if channel_id is None:
            warn(self, "Escolha um canal na lista.")
            return
        current = next(c for c in self.ctx.repo.list_channels() if c["id"] == channel_id)
        self.ctx.repo.set_channel_paused(channel_id, not current["paused"])
        self.refresh()

    def remove_channel(self) -> None:
        channel_id = selected_id(self.channels)
        if channel_id is None:
            warn(self, "Escolha um canal na lista.")
            return
        if confirm(self, "Remover o canal apaga também os vídeos e as curiosidades dele. Continuar?"):
            self.ctx.repo.remove_channel(channel_id)
            self.refresh()

    def _interval_changed(self, minutes: int) -> None:
        self.ctx.repo.set_setting("radar_interval_min", str(minutes))
        self.timer.start(minutes * 60 * 1000)

    def _automatic_check(self) -> None:
        if not self.ctx.busy:
            self.check_now()

    def check_now(self) -> None:
        repo = self.ctx.repo
        channels = [
            (c["id"], ChannelRef(c["youtube_id"], c["uploads_playlist"]),
             repo.known_video_ids(c["id"]))
            for c in repo.list_channels()
            if not c["paused"]
        ]
        if not channels:
            self.ctx.message.emit("Radar: nenhum canal ativo para verificar.")
            return
        # Cada canal gasta até 3 unidades.
        if not self._quota_allows(3 * len(channels)):
            self.ctx.message.emit(
                "Radar pausado por hoje: a cota diária da YouTube Data API acabou."
            )
            return
        radar = self.ctx.services.radar

        def work(progress, cancelled):
            found, units = [], 0
            for channel_id, reference, known in channels:
                result = radar.check(reference, known, progress, cancelled)
                units += result.units
                found.extend((channel_id, video) for video in result.videos)
            return found, units

        def done(result) -> str:
            found, units = result
            repo.add_usage("youtube", units)
            new = 0
            for channel_id, video in found:
                added = repo.add_video(
                    channel_id,
                    validate_video_id(video.youtube_id),
                    clean_text(video.title, 200, required=True),
                    clean_text(video.published_at, 32, required=True),
                    max(int(video.duration_s), 0),
                )
                new += added is not None
            self.refresh()
            return f"Radar: {new} vídeo(s) novo(s) em {len(channels)} canal(is)."

        self.ctx.run_task("Verificação do radar", work, done)

    # ----- vídeos -----

    def _selected_video(self):
        video_id = selected_id(self.videos)
        if video_id is None:
            warn(self, "Escolha um vídeo na lista.")
            return None
        return next(v for v in self.ctx.repo.list_videos() if v["id"] == video_id)

    def analyze_selected(self) -> None:
        video = self._selected_video()
        if video is None:
            return
        if video["used"]:
            warn(self, "Este vídeo já foi usado. Cada vídeo de origem só vira publicação uma vez.")
            return
        if video["status"] == "analisado":
            warn(self, "Este vídeo já foi analisado. Veja as curiosidades dele na tela Curiosidades.")
            return
        repo = self.ctx.repo
        watched = repo.usage_today().get("gemini_video_s", 0)
        if (
            not self.ctx.demo
            and watched + video["duration_s"] > GEMINI_FREE_DAILY_VIDEO_S
            and not confirm(
                self,
                "Com este vídeo, o total analisado hoje passa de 8 horas, que é o limite "
                "do plano gratuito do Gemini. Continuar mesmo assim?",
            )
        ):
            return
        analyst = self.ctx.services.analyst
        video_id, youtube_id = video["id"], video["youtube_id"]
        duration, theme = video["duration_s"], video["theme"]

        def work(progress, cancelled):
            return analyst.analyze(youtube_id, duration, theme, progress, cancelled)

        def done(result) -> str:
            repo.add_usage("gemini", result.requests)
            repo.add_usage("gemini_video_s", result.video_seconds)
            count = repo.add_curiosities(video_id, result.drafts)
            self.refresh()
            return f"Análise concluída: {count} curiosidades extraídas."

        self.ctx.run_task("Análise do vídeo", work, done)

    def open_selected(self) -> None:
        video = self._selected_video()
        if video is not None:
            open_url(self, video_url(video["youtube_id"]))
