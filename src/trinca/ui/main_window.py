"""Janela principal: barra lateral, telas e faixa de tarefas."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..config import APP_NAME
from ..context import AppContext
from . import theme
from .pages.curiosities import CuriositiesPage
from .pages.dashboard import DashboardPage
from .pages.history import HistoryPage
from .pages.importing import ImportPage
from .pages.publishing import PublishingPage
from .pages.radar import RadarPage
from .pages.review import ReviewPage
from .pages.scripts import ScriptsPage
from .pages.settings import SettingsPage
from .widgets import LogoWidget, app_icon, button, label

PAGES = (
    ("painel", "Painel", DashboardPage),
    ("radar", "Radar de temas e canais", RadarPage),
    ("curiosidades", "Curiosidades", CuriositiesPage),
    ("roteiros", "Roteiros", ScriptsPage),
    ("importacao", "Importação e narração", ImportPage),
    ("revisao", "Montagem e revisão", ReviewPage),
    ("publicacao", "Publicação", PublishingPage),
    ("historico", "Histórico", HistoryPage),
    ("configuracoes", "Configurações", SettingsPage),
)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(1080, 680)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        main = QHBoxLayout()
        main.setSpacing(0)
        outer.addLayout(main, 1)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 16)
        side.setSpacing(4)
        brand = QHBoxLayout()
        brand.addWidget(LogoWidget())
        brand.addWidget(label(APP_NAME, "Brand"), 1)
        side.addLayout(brand)
        side.addSpacing(14)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.nav: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, title, page_class in PAGES:
            page = page_class(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
            nav = QPushButton(title)
            nav.setObjectName("Nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda _=False, key=key: self.show_page(key))
            group.addButton(nav)
            self.nav[key] = nav
            side.addWidget(nav)
        side.addStretch(1)
        if ctx.demo:
            badge = QLabel("MODO DE DEMONSTRAÇÃO\nDados fictícios, nada é publicado.")
        else:
            badge = QLabel("MODO REAL\nAinda simulados: " + ", ".join(ctx.services.simulated) + ".")
        badge.setObjectName("DemoBadge")
        badge.setWordWrap(True)
        side.addWidget(badge)
        main.addWidget(sidebar)
        main.addWidget(self.stack, 1)

        strip = QWidget()
        strip.setObjectName("TaskStrip")
        strip.setFixedHeight(46)
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(18, 6, 18, 6)
        self.task_label = QLabel("Pronto.")
        self.task_bar = QProgressBar()
        self.task_bar.setFixedWidth(220)
        self.task_bar.setTextVisible(False)
        self.task_bar.hide()
        self.cancel_button = button("Cancelar", ctx.cancel_task)
        self.cancel_button.hide()
        self.retry_button = button("Tentar de novo", ctx.retry)
        self.retry_button.hide()
        strip_row.addWidget(self.task_label, 1)
        strip_row.addWidget(self.task_bar)
        strip_row.addWidget(self.cancel_button)
        strip_row.addWidget(self.retry_button)
        outer.addWidget(strip)

        ctx.navigate.connect(self.show_page)
        ctx.task_started.connect(self._task_started)
        ctx.task_progress.connect(self._task_progress)
        ctx.task_ended.connect(self._task_ended)
        ctx.message.connect(self._message)
        self.show_page("painel")

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self.nav[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        self.pages[key].refresh()

    def _message(self, text: str, color: str = theme.TEXT) -> None:
        self.task_label.setText(text)
        self.task_label.setStyleSheet(f"color: {color};")

    def _task_started(self, text: str) -> None:
        self._message(f"{text}…")
        self.task_bar.setValue(0)
        self.task_bar.show()
        self.cancel_button.show()
        self.retry_button.hide()

    def _task_progress(self, percent: int, step: str) -> None:
        self.task_bar.setValue(percent)
        self._message(step)

    def _task_ended(self, text: str, ok: bool) -> None:
        self.task_bar.hide()
        self.cancel_button.hide()
        self.retry_button.setVisible(not ok and self.ctx.can_retry)
        self._message(text, theme.TEXT if ok else theme.DANGER)

    def closeEvent(self, event) -> None:  # noqa: N802 - nome definido pelo Qt
        self.ctx.cancel_task()
        super().closeEvent(event)
