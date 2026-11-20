"""Biblioteca: assistir aos cortes prontos, ver os arquivos brutos e excluir arquivos."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QWidget, QVBoxLayout

from ...context import AppContext
from ...pipeline.media import cuts_dir, raw_dir
from ...security import ValidationError, ensure_within
from ..widgets import Card, Page, button, confirm, fill_table, label, make_table, row, selected_id, warn
from .review import VideoPlayer


def _size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "—"
    return f"{size / 1_048_576:.1f} MB" if size >= 1_048_576 else f"{size / 1024:.0f} KB"


def _modified(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    except OSError:
        return "—"


def _open_folder(folder: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class LibraryPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Biblioteca",
            "Assista aos cortes prontos, veja os arquivos brutos baixados e apague o que não "
            "precisa mais. Cortes e brutos ficam em pastas separadas na sua máquina.",
        )
        self.ctx = ctx
        self._cuts: dict[int, Path] = {}
        self._raws: dict[int, Path] = {}
        self.player: VideoPlayer | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_cuts_tab(), "Cortes prontos")
        tabs.addTab(self._build_raw_tab(), "Arquivos brutos")
        self.root.addWidget(tabs, 1)
        self.folders = label("", "Muted")
        self.root.addWidget(self.folders)

    # ----- abas -----

    def _build_cuts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setSpacing(12)
        left = QVBoxLayout()
        self.cut_table = make_table(["Vídeo", "Tamanho", "Criado em"])
        self.cut_table.itemSelectionChanged.connect(self._play_selected)
        left.addWidget(self.cut_table, 1)
        left.addLayout(row(
            button("Excluir corte", self.delete_cut),
            button("Abrir pasta", lambda: _open_folder(cuts_dir(self.ctx.output_dir()))),
        ))
        layout.addLayout(left, 3)
        self.player_card = Card("Assistir")
        self.player_note = label("Escolha um corte da lista para assistir.", "Muted")
        self.player_card.body.addWidget(self.player_note)
        try:
            self.player = VideoPlayer()
            self.player.setVisible(False)
            self.player_card.body.addWidget(self.player, 0, Qt.AlignmentFlag.AlignHCenter)
        except Exception:  # noqa: BLE001 - sem QtMultimedia o player não existe
            self.player = None
            self.player_note.setText("O player não está disponível. Use “Abrir pasta”.")
        self.player_card.body.addStretch(1)
        layout.addWidget(self.player_card, 2)
        return tab

    def _build_raw_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.raw_table = make_table(["Arquivo", "Tamanho", "Baixado em"])
        layout.addWidget(self.raw_table, 1)
        layout.addLayout(row(
            button("Excluir arquivo bruto", self.delete_raw),
            button("Abrir pasta", lambda: _open_folder(raw_dir(self.ctx.output_dir()))),
        ))
        return tab

    # ----- dados -----

    def refresh(self) -> None:
        repo = self.ctx.repo
        output = self.ctx.output_dir()
        self._cuts = {}
        cut_rows = []
        for script in repo.list_scripts():
            path = Path(script["render_path"]) if script["render_path"] else None
            if path is not None and path.is_absolute() and path.is_file():
                self._cuts[script["id"]] = path
                cut_rows.append((script["id"], (script["title"], _size(path), _modified(path))))
        fill_table(self.cut_table, cut_rows)

        self._raws = {}
        raw_rows = []
        folder = raw_dir(output)
        for index, path in enumerate(sorted(folder.iterdir(), key=lambda p: -p.stat().st_mtime)):
            if path.is_file():
                self._raws[index] = path
                raw_rows.append((index, (path.name, _size(path), _modified(path))))
        fill_table(self.raw_table, raw_rows)
        self.folders.setText(f"Cortes: {cuts_dir(output)}   |   Brutos: {folder}")
        self._play_selected()

    # ----- player -----

    def _play_selected(self) -> None:
        script_id = selected_id(self.cut_table)
        path = self._cuts.get(script_id) if script_id is not None else None
        if self.player is None:
            return
        self.player.setVisible(path is not None)
        self.player_note.setVisible(path is None)
        if path is not None:
            self.player.load(str(path))
        else:
            self.player.stop()

    # ----- exclusão -----

    def delete_cut(self) -> None:
        script_id = selected_id(self.cut_table)
        path = self._cuts.get(script_id) if script_id is not None else None
        if path is None:
            warn(self, "Escolha um corte da lista.")
            return
        if not confirm(
            self,
            f"Excluir o corte “{path.name}” do disco? O roteiro continua no app e pode ser "
            "renderizado de novo na tela Montagem e revisão.",
        ):
            return
        try:
            ensure_within(cuts_dir(self.ctx.output_dir()), path)
        except ValidationError as exc:
            warn(self, str(exc))
            return
        if self.player is not None:
            self.player.stop()
            self.player.unload()
        for target in (path, path.with_suffix(".jpg")):
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                warn(self, f"Não consegui excluir {target.name}: {exc.strerror or exc}")
                return
        repo = self.ctx.repo
        script = repo.get_script(script_id)
        fields = {"render_path": ""}
        if script["status"] == "aprovado":
            fields["status"] = "aguardando_revisao"
        repo.update_script(script_id, **fields)
        self.ctx.message.emit("Corte excluído.")
        self.refresh()

    def delete_raw(self) -> None:
        index = selected_id(self.raw_table)
        path = self._raws.get(index) if index is not None else None
        if path is None:
            warn(self, "Escolha um arquivo bruto da lista.")
            return
        if not confirm(
            self,
            f"Excluir o arquivo bruto “{path.name}” do disco? Se algum roteiro o usa, o bloco "
            "volta a ficar sem vídeo e você precisará baixar de novo.",
        ):
            return
        try:
            ensure_within(raw_dir(self.ctx.output_dir()), path)
            path.unlink(missing_ok=True)
        except (ValidationError, OSError) as exc:
            warn(self, f"Não consegui excluir o arquivo: {exc}")
            return
        repo = self.ctx.repo
        for script in repo.list_scripts():
            for block in repo.list_blocks(script["id"]):
                if block["media_path"] == str(path):
                    repo.update_block(block["id"], media_path="")
                    repo.update_script(script["id"], render_path="", status="aguardando_gravacao")
        self.ctx.message.emit("Arquivo bruto excluído.")
        self.refresh()
