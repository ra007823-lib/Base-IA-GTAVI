"""Curiosidades: momentos extraídos dos vídeos e seleção para o roteiro."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QTreeWidget, QTreeWidgetItem,
)

from ...context import AppContext, to_inputs
from ...security import video_url
from ..widgets import (
    Card, Page, button, confirm, fmt_time, label, open_url, row, status_text, warn,
)


def _blocked(row) -> bool:
    """A curiosidade não pode mais ser usada: o vídeo dela já foi para outro roteiro."""
    return bool(row["video_used"]) and row["status"] != "usada"

_FILTERS = (
    ("Todas", None),
    ("Novas", "nova"),
    ("Selecionadas", "selecionada"),
    ("Descartadas", "descartada"),
    ("Usadas", "usada"),
)


class CuriositiesPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Curiosidades",
            "Escolha os momentos que vão virar vídeo. O roteiro conta cada um com texto "
            "próprio e cita o canal de origem. Cada vídeo de origem só pode ser usado uma vez.",
        )
        self.ctx = ctx
        self._rows: dict[int, object] = {}

        self.filter = QComboBox()
        for text, value in _FILTERS:
            self.filter.addItem(text, value)
        self.filter.currentIndexChanged.connect(lambda _: self.refresh())
        self.root.addLayout(row(label("Mostrar"), self.filter))

        columns = QHBoxLayout()
        columns.setSpacing(12)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Curiosidade", "Momento", "Estado"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._show_detail)
        columns.addWidget(self.tree, 3)

        detail = Card("Detalhes")
        self.detail_title = label("Escolha uma curiosidade na lista.", "H2")
        self.detail_source = label("", "Muted")
        self.detail_text = label("")
        self.detail_scene = label("", "Muted")
        for widget in (self.detail_title, self.detail_source, self.detail_text, self.detail_scene):
            detail.body.addWidget(widget)
        detail.body.addStretch(1)
        detail.body.addWidget(button("Abrir o momento no vídeo original", self.open_moment))
        columns.addWidget(detail, 2)
        self.root.addLayout(columns, 1)

        self.generate_button = button("Gerar roteiro", self.generate, True)
        self.root.addLayout(
            row(
                button("Selecionar", lambda: self.set_status("selecionada")),
                button("Descartar", lambda: self.set_status("descartada")),
                button("Voltar para nova", lambda: self.set_status("nova")),
                self.generate_button,
            )
        )

    def refresh(self) -> None:
        repo = self.ctx.repo
        rows = repo.list_curiosities(self.filter.currentData())
        self._rows = {r["id"]: r for r in rows}
        chosen = set(self._selected_ids())
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[int, QTreeWidgetItem] = {}
        for r in rows:
            parent = groups.get(r["video_id"])
            if parent is None:
                parent = QTreeWidgetItem([f"{r['video_title']} — {r['channel_name']}", "", ""])
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(parent)
                parent.setFirstColumnSpanned(True)
                groups[r["video_id"]] = parent
            text, color = status_text("indisponivel" if _blocked(r) else r["status"])
            item = QTreeWidgetItem([r["title"], fmt_time(r["start_s"]), f"● {text}"])
            item.setForeground(2, QColor(color))
            item.setData(0, Qt.ItemDataRole.UserRole, r["id"])
            parent.addChild(item)
            if r["id"] in chosen:
                item.setSelected(True)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self._show_detail()
        selected_count = len(self._available_selected())
        self.generate_button.setText(f"Gerar roteiro com as selecionadas ({selected_count})")
        self.generate_button.setEnabled(selected_count > 0)

    def _available_selected(self) -> list:
        """Curiosidades selecionadas cujo vídeo ainda não foi usado."""
        return [r for r in self.ctx.repo.list_curiosities("selecionada") if not _blocked(r)]

    def _selected_ids(self) -> list[int]:
        ids = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()]
        return [i for i in ids if i is not None]

    def _show_detail(self) -> None:
        ids = self._selected_ids()
        current = self._rows.get(ids[0]) if ids else None
        if current is None:
            self.detail_title.setText("Escolha uma curiosidade na lista.")
            for widget in (self.detail_source, self.detail_text, self.detail_scene):
                widget.setText("")
            return
        self.detail_title.setText(current["title"])
        self.detail_source.setText(
            f"{current['channel_name']} · {fmt_time(current['start_s'])} a "
            f"{fmt_time(current['end_s'])}"
        )
        self.detail_text.setText(current["description"])
        self.detail_scene.setText(f"Cena para gravar: {current['scene_hint']}")

    def set_status(self, status: str) -> None:
        ids = [
            i for i in self._selected_ids()
            if self._rows[i]["status"] != "usada" and not _blocked(self._rows[i])
        ]
        if not ids:
            warn(self, "Escolha ao menos uma curiosidade disponível. As de um vídeo que já "
                       "foi usado em outro roteiro ficam bloqueadas.")
            return
        self.ctx.repo.set_curiosity_status(ids, status)
        self.refresh()

    def open_moment(self) -> None:
        ids = self._selected_ids()
        if not ids:
            warn(self, "Escolha uma curiosidade na lista.")
            return
        current = self._rows[ids[0]]
        open_url(self, video_url(current["video_youtube_id"], current["start_s"]))

    def generate(self) -> None:
        repo = self.ctx.repo
        rows = self._available_selected()
        limit = int(repo.get_setting("curiosities_per_video"))
        if len(rows) > limit:
            if not confirm(
                self,
                f"Há {len(rows)} curiosidades selecionadas e o limite por vídeo é {limit}. "
                f"O roteiro vai usar as {limit} primeiras. As que sobrarem de um vídeo usado "
                "neste roteiro ficam bloqueadas, porque cada vídeo de origem só pode ser "
                "usado uma vez. Continuar?",
            ):
                return
            rows = rows[:limit]
        items = to_inputs(rows)
        max_seconds = int(repo.get_setting("max_duration_s"))
        writer = self.ctx.services.writer

        def work(progress, cancelled):
            return writer.write(items, max_seconds, progress, cancelled)

        def done(draft) -> str:
            repo.add_usage("claude")
            repo.create_script(draft.title, draft.blocks)
            self.refresh()
            self.ctx.navigate.emit("roteiros")
            return f"Roteiro criado: {draft.title}"

        self.ctx.run_task("Criação do roteiro", work, done)
