"""Ponto de entrada: python -m trinca"""

from __future__ import annotations

import logging
import sys

if __package__ in (None, ""):  # executado como arquivo (botão Run do IDE): usa o pacote instalado
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "trinca"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .config import APP_ID, APP_NAME, load_demo_mode, save_demo_mode
from .context import build_context
from .security import RedactingFilter
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


class Launcher:
    """Abre a janela do modo escolhido e a troca quando o usuário muda de modo."""

    def __init__(self, context_factory=build_context) -> None:
        self._factory = context_factory
        self.window: MainWindow | None = None

    def start(self, demo: bool) -> None:
        ctx = self._factory(demo=demo)
        ctx.switch_mode.connect(self._switch)
        previous = self.window
        self.window = MainWindow(ctx)
        self.window.show()
        if previous is not None:
            previous.close()
            previous.ctx.repo.close()
            previous.deleteLater()

    def _switch(self, demo: bool) -> None:
        save_demo_mode(demo)
        # Troca depois que o clique terminar, para não destruir a janela em uso.
        QTimer.singleShot(0, lambda: self.start(demo))


def main() -> int:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler])

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    apply_theme(app)
    launcher = Launcher()
    launcher.start(load_demo_mode())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
