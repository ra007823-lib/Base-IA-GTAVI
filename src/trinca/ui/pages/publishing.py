"""Publicação: textos por plataforma, YouTube pelo navegador e pacote para as demais."""

from __future__ import annotations

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QTabWidget,
    QWidget,
)

from ...config import PLATFORM_LABELS, PLATFORMS, UPLOAD_PAGES
from ...context import AppContext, to_sources
from ...pipeline.contracts import PlatformCopy
from ...pipeline.publishing import build_package
from ...pipeline.script import manual_copy_prompt, missing_credits, parse_pasted_copy
from ...security import ValidationError, clean_text, is_allowed_url
from ..paste_dialog import PasteDialog
from ..widgets import button, chip, clear_layout, confirm, label, open_url, Page, row, warn


class PlatformTab(QWidget):
    def __init__(self, page: "PublishingPage", platform: str) -> None:
        super().__init__()
        self.platform = platform
        self.publication_id: int | None = None
        form = QFormLayout(self)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        self.status_row = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(100)
        self.description = QPlainTextEdit()
        self.hashtags = QLineEdit()
        self.hashtags.setMaxLength(300)
        self.when = QDateTimeEdit()
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.package = label("", "Muted")
        form.addRow("Estado", self.status_row)
        form.addRow("Título", self.title)
        form.addRow("Descrição", self.description)
        form.addRow("Hashtags", self.hashtags)
        form.addRow("Horário", self.when)
        actions = [button("Salvar", lambda: page.save(self))]
        if platform == "youtube":
            actions.append(button("Agendar no YouTube", lambda: page.schedule_youtube(self), True))
        else:
            actions.append(button("Gerar pacote de publicação", lambda: page.make_package(self), True))
            actions.append(button("Abrir página de upload",
                                  lambda: open_url(self, UPLOAD_PAGES[platform])))
            actions.append(button("Marcar como publicado", lambda: page.mark_published(self)))
            form.addRow("Pacote", self.package)
        form.addRow(row(*actions))

    def load(self, publication) -> None:
        clear_layout(self.status_row)
        self.publication_id = publication["id"] if publication else None
        self.setEnabled(publication is not None)
        if publication is None:
            self.title.clear()
            self.description.clear()
            self.hashtags.clear()
            self.package.setText("")
            self.status_row.addWidget(label("Gere os textos para começar.", "Muted"))
            return
        self.status_row.addWidget(chip(publication["status"]))
        self.status_row.addStretch(1)
        self.title.setText(publication["title"])
        self.description.setPlainText(publication["description"])
        self.hashtags.setText(publication["hashtags"])
        stored = QDateTime.fromString(publication["scheduled_at"], "yyyy-MM-ddTHH:mm:ss")
        self.when.setDateTime(
            stored if stored.isValid() else QDateTime.currentDateTime().addSecs(3600)
        )
        self.package.setText(publication["package_path"] or "Ainda não gerado")

    def copy(self) -> PlatformCopy:
        return PlatformCopy(
            self.platform,
            clean_text(self.title.text(), 100, required=True),
            clean_text(self.description.toPlainText(), 2200, required=True),
            clean_text(self.hashtags.text(), 300),
        )

    def scheduled_at(self) -> str:
        return self.when.dateTime().toString("yyyy-MM-ddTHH:mm:ss")


class PublishingPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            "Publicação",
            "O YouTube é enviado pelo YouTube Studio, numa janela do Chrome controlada pelo app. Para Instagram e TikTok o app monta o "
            "pacote e abre a página oficial de upload.",
        )
        self.ctx = ctx
        self._script_id: int | None = None

        self.scripts = QComboBox()
        self.scripts.setMinimumWidth(420)
        self.scripts.currentIndexChanged.connect(lambda _: self._load_current())
        self.copy_button = button("Gerar textos", self.generate_copy)
        self.paste_button = button("Escrever com o Claude (colar)", self.generate_copy_pasted)
        self.root.addLayout(
            row(label("Vídeo aprovado"), self.scripts, self.copy_button, self.paste_button)
        )

        self.tabs = QTabWidget()
        self.platform_tabs = {}
        for platform in PLATFORMS:
            tab = PlatformTab(self, platform)
            self.platform_tabs[platform] = tab
            self.tabs.addTab(tab, PLATFORM_LABELS[platform])
        self.root.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        keep = self._script_id
        self.scripts.blockSignals(True)
        self.scripts.clear()
        for script in self.ctx.repo.list_scripts(("aprovado",)):
            self.scripts.addItem(script["title"], script["id"])
        index = self.scripts.findData(keep)
        if index >= 0:
            self.scripts.setCurrentIndex(index)
        self.scripts.blockSignals(False)
        self._load_current()

    def _load_current(self) -> None:
        self._script_id = self.scripts.currentData()
        self.copy_button.setEnabled(self._script_id is not None)
        self.paste_button.setEnabled(self._script_id is not None)
        publications = (
            {p["platform"]: p for p in self.ctx.repo.list_publications(self._script_id)}
            if self._script_id
            else {}
        )
        for platform, tab in self.platform_tabs.items():
            tab.load(publications.get(platform))

    def _save_copies(self, script_id: int, copies) -> None:
        for copy in copies:
            if copy.platform not in PLATFORMS:
                raise ValidationError("O roteirista devolveu uma plataforma desconhecida.")
            self.ctx.repo.upsert_publication(
                script_id, copy.platform, clean_text(copy.title, 100, required=True),
                clean_text(copy.description, 2200, required=True),
                clean_text(copy.hashtags, 300),
            )

    def generate_copy_pasted(self) -> None:
        """Textos escritos no chat do Claude: o app monta o pedido e valida a resposta."""
        if self._script_id is None:
            return
        repo = self.ctx.repo
        script_id = self._script_id
        if repo.list_publications(script_id) and not confirm(
            self, "Gerar os textos de novo substitui o que já está escrito. Continuar?"
        ):
            return
        title = repo.get_script(script_id)["title"]
        text = "\n".join(block["text"] for block in repo.list_blocks(script_id))
        sources = to_sources(repo.script_sources(script_id))
        dialog = PasteDialog(
            self, "Textos com o Claude", manual_copy_prompt(title, text),
            lambda answer: parse_pasted_copy(answer, sources),
        )
        if dialog.exec() and dialog.result_value is not None:
            try:
                self._save_copies(script_id, dialog.result_value)
            except ValidationError as exc:
                warn(self, str(exc))
                return
            self.refresh()
            self.ctx.message.emit("Textos de publicação gerados. Revise antes de publicar.")

    def generate_copy(self) -> None:
        if self._script_id is None:
            return
        repo = self.ctx.repo
        script_id = self._script_id
        if repo.list_publications(script_id) and not confirm(
            self, "Gerar os textos de novo substitui o que já está escrito. Continuar?"
        ):
            return
        title = repo.get_script(script_id)["title"]
        text = "\n".join(block["text"] for block in repo.list_blocks(script_id))
        sources = to_sources(repo.script_sources(script_id))
        writer = self.ctx.services.writer

        def work(progress, cancelled):
            return writer.platform_copy(title, text, sources, progress, cancelled)

        def done(copies) -> str:
            repo.add_usage(self.ctx.writer_name)
            self._save_copies(script_id, copies)
            self.refresh()
            return "Textos de publicação gerados. Revise antes de publicar."

        self.ctx.run_task("Textos de publicação", work, done)

    # ----- ações de cada plataforma -----

    def _checked_copy(self, tab: PlatformTab, need_credit: bool) -> PlatformCopy | None:
        """Lê os campos da aba, salva e confere o crédito obrigatório."""
        if tab.publication_id is None or self._script_id is None:
            return None
        try:
            copy = tab.copy()
        except ValidationError:
            warn(self, "O título e a descrição não podem ficar vazios.")
            return None
        if need_credit:
            sources = to_sources(self.ctx.repo.script_sources(self._script_id))
            missing = missing_credits(copy.description, sources)
            if missing:
                names = ", ".join(source.channel for source in missing)
                warn(
                    self,
                    "A descrição precisa citar o canal de origem e trazer o link do vídeo "
                    f"original. Falta o crédito de: {names}.",
                )
                return None
        self.ctx.repo.update_publication(
            tab.publication_id, title=copy.title, description=copy.description,
            hashtags=copy.hashtags, scheduled_at=tab.scheduled_at(),
        )
        return copy

    def save(self, tab: PlatformTab) -> None:
        if self._checked_copy(tab, need_credit=False) is not None:
            self.ctx.message.emit(f"{PLATFORM_LABELS[tab.platform]}: textos salvos.")
            self._load_current()

    def schedule_youtube(self, tab: PlatformTab) -> None:
        copy = self._checked_copy(tab, need_credit=True)
        if copy is None:
            return
        repo = self.ctx.repo
        publication_id = tab.publication_id
        render_path = repo.get_script(self._script_id)["render_path"]
        when = tab.scheduled_at()
        youtube = self.ctx.services.youtube

        def work(progress, cancelled):
            return youtube.schedule(copy, render_path, when, progress, cancelled)

        demo = self.ctx.demo

        def done(url) -> str:
            repo.update_publication(
                publication_id, status="agendado", url=url if is_allowed_url(url) else ""
            )
            self.refresh()
            if demo:
                return "YouTube: agendamento simulado. Nada foi enviado."
            return "YouTube: vídeo enviado e agendado pelo YouTube Studio."

        self.ctx.run_task("Agendamento no YouTube", work, done)

    def make_package(self, tab: PlatformTab) -> None:
        copy = self._checked_copy(tab, need_credit=True)
        if copy is None:
            return
        repo = self.ctx.repo
        script = repo.get_script(self._script_id)
        try:
            folder = build_package(
                self.ctx.output_dir(), script["id"], script["title"], copy,
                tab.scheduled_at(), script["render_path"],
            )
        except (ValidationError, OSError) as exc:
            warn(self, f"Não foi possível criar o pacote: {exc}")
            return
        repo.update_publication(tab.publication_id, package_path=str(folder))
        self.ctx.message.emit(f"Pacote criado em {folder}")
        self._load_current()

    def mark_published(self, tab: PlatformTab) -> None:
        if self._checked_copy(tab, need_credit=True) is None:
            return
        name = PLATFORM_LABELS[tab.platform]
        if confirm(self, f"Confirmar que o vídeo já foi publicado no {name}?"):
            self.ctx.repo.update_publication(tab.publication_id, status="publicado")
            self._load_current()
