"""Histórico: tudo o que foi preparado ou publicado."""

from __future__ import annotations

from ...config import PLATFORM_LABELS
from ...context import AppContext
from ..widgets import (
    Page, button, fill_table, fmt_date, make_table, open_url, row, selected_id, warn,
)


class HistoryPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Histórico",
            "Vídeos produzidos, com plataforma, estado e canais de origem das curiosidades.",
        )
        self.ctx = ctx
        self.table = make_table(
            ["Vídeo", "Plataforma", "Estado", "Atualizado", "Origem", "Link ou pacote"]
        )
        self.root.addWidget(self.table, 1)
        self.root.addLayout(row(button("Abrir link da publicação", self.open_link)))

    def refresh(self) -> None:
        repo = self.ctx.repo
        rows = []
        for p in repo.list_publications():
            origins = ", ".join(
                sorted({s["channel_name"] for s in repo.script_sources(p["script_id"])})
            )
            rows.append(
                (p["id"], (p["script_title"], PLATFORM_LABELS[p["platform"]],
                           ("estado", p["status"]), fmt_date(p["updated_at"]),
                           origins or "—", p["url"] or p["package_path"] or "—"))
            )
        fill_table(self.table, rows)

    def open_link(self) -> None:
        publication_id = selected_id(self.table)
        if publication_id is None:
            warn(self, "Escolha uma publicação na lista.")
            return
        url = next(p["url"] for p in self.ctx.repo.list_publications() if p["id"] == publication_id)
        if not url:
            warn(self, "Esta publicação ainda não tem link.")
            return
        open_url(self, url)
