"""Contexto compartilhado pelas telas: banco, cofre, serviços e tarefas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from .config import data_dir, default_output_dir
from .credentials import CredentialError, CredentialStore
from .db import Repository
from .demo_data import DEMO_CHANNELS, DEMO_VIDEOS
from .pipeline.analysis import DemoAnalyst, GeminiAnalyst, VideoAnalyst
from .pipeline.assembly import DEMO_MEDIA, DEMO_RENDER, Assembler, DemoAssembler, FfmpegAssembler
from .pipeline.download import DemoDownloader, SourceDownloader, YtDlpDownloader
from .pipeline.contracts import CuriosityInput, ServiceError, Source, parse_curiosities
from .pipeline.narration import DemoSpeech, LocalSpeech, SpeechProvider, estimate_duration
from .pipeline.publishing import DemoYouTube, Publisher
from .pipeline.radar import DemoRadar, RadarSource
from .pipeline.script import ClaudeWriter, DemoWriter, GeminiWriter, RoutedWriter, ScriptWriter
from .pipeline.youtube_browser import BrowserYouTube
from .pipeline.youtube_search import YtDlpRadar
from .security import ValidationError, validate_model_name
from .tasks import Task, TaskFn

# Etapas que continuam simuladas no modo real até as etapas 3 e 4 do projeto.
STILL_SIMULATED: tuple[str, ...] = ()


@dataclass
class Services:
    radar: RadarSource
    analyst: VideoAnalyst
    writer: ScriptWriter
    speech: SpeechProvider
    assembler: Assembler
    youtube: Publisher
    downloader: SourceDownloader
    simulated: tuple[str, ...] = ()


def demo_services(delay: float | None = None) -> Services:
    kwargs = {} if delay is None else {"delay": delay}
    return Services(
        radar=DemoRadar(**kwargs),
        analyst=DemoAnalyst(**kwargs),
        writer=DemoWriter(**kwargs),
        speech=DemoSpeech(**kwargs),
        assembler=DemoAssembler(**kwargs),
        youtube=DemoYouTube(**kwargs),
        downloader=DemoDownloader(**kwargs),
    )


def real_services(
    credentials: CredentialStore, models: dict[str, str], delay: float | None = None
) -> Services:
    """Radar, análise e roteiro reais. As chaves são lidas do cofre a cada pedido.

    `models` é um dicionário mantido pela thread principal, porque as tarefas
    em segundo plano não podem ler o banco.
    """
    kwargs = {} if delay is None else {"delay": delay}
    return Services(
        radar=YtDlpRadar(),
        analyst=GeminiAnalyst(lambda: credentials.get("gemini"), lambda: models["gemini"]),
        writer=RoutedWriter(
            lambda: models.get("writer", "gemini"),
            GeminiWriter(lambda: credentials.get("gemini"), lambda: models["gemini"]),
            ClaudeWriter(lambda: credentials.get("claude"), lambda: models["claude"]),
        ),
        speech=LocalSpeech(),
        assembler=FfmpegAssembler(),
        youtube=BrowserYouTube(),
        downloader=YtDlpDownloader(),
        simulated=STILL_SIMULATED,
    )


def to_inputs(rows: Sequence) -> list[CuriosityInput]:
    return [
        CuriosityInput(
            id=row["id"], title=row["title"], description=row["description"],
            scene_hint=row["scene_hint"], channel=row["channel_name"],
            video_youtube_id=row["video_youtube_id"], start_s=row["start_s"],
            theme=row["theme"],
        )
        for row in rows
    ]


def to_sources(rows: Sequence) -> list[Source]:
    return [
        Source(row["channel_name"], row["video_youtube_id"], row["video_title"]) for row in rows
    ]


class AppContext(QObject):
    navigate = Signal(str)
    task_started = Signal(str)
    task_progress = Signal(int, str)
    task_ended = Signal(str, bool)  # mensagem, sucesso
    message = Signal(str)
    switch_mode = Signal(bool)  # True = demonstração

    def __init__(
        self, repo: Repository, credentials: CredentialStore, services: Services, demo: bool,
        models: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.repo = repo
        self.credentials = credentials
        self.services = services
        self.demo = demo
        self.models = models if models is not None else {}
        self._task: Task | None = None
        self._last: tuple[str, TaskFn, Callable] | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None

    @property
    def can_retry(self) -> bool:
        return self._last is not None and not self.busy

    def set_model(self, kind: str, name: str) -> None:
        """Troca o modelo do Gemini ('gemini') ou do Claude ('claude')."""
        if kind not in ("gemini", "claude"):
            raise KeyError(kind)
        value = validate_model_name(name)
        self.repo.set_setting(f"{kind}_model", value)
        self.models[kind] = value

    def set_writer(self, provider: str) -> None:
        """Escolhe quem escreve roteiros e textos: 'gemini' ou 'claude'."""
        if provider not in ("gemini", "claude"):
            raise KeyError(provider)
        self.repo.set_setting("writer_provider", provider)
        self.models["writer"] = provider

    @property
    def writer_name(self) -> str:
        """Serviço contado no uso diário quando o roteirista é chamado."""
        return self.models.get("writer", "claude") if not self.demo else "claude"

    def output_dir(self) -> Path:
        configured = self.repo.get_setting("output_dir")
        return Path(configured) if configured else default_output_dir()

    def run_task(self, label: str, fn: TaskFn, on_done: Callable[[object], str | None]) -> bool:
        """Roda fn em segundo plano. on_done recebe o resultado na thread principal."""
        if self.busy:
            self.message.emit("Aguarde a tarefa atual terminar.")
            return False
        task = Task(fn)
        self._task = task
        self._last = (label, fn, on_done)
        task.signals.progress.connect(self.task_progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        task.signals.cancelled.connect(self._on_cancelled)
        self.task_started.emit(label)
        QThreadPool.globalInstance().start(task)
        return True

    def cancel_task(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def retry(self) -> None:
        if self.can_retry:
            self.run_task(*self._last)

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        label, _, on_done = self._last
        self._task = None
        try:
            text = on_done(result)
        except (ValidationError, CredentialError, ServiceError) as exc:
            self.task_ended.emit(f"{label}: {exc}", False)
            return
        self._last = None
        self.task_ended.emit(text or f"{label}: concluído.", True)

    @Slot(str)
    def _on_failed(self, error: str) -> None:
        label = self._last[0]
        self._task = None
        self.task_ended.emit(f"Falha em “{label}”: {error}", False)

    @Slot()
    def _on_cancelled(self) -> None:
        label = self._last[0]
        self._task = None
        self._last = None
        self.task_ended.emit(f"{label}: cancelado.", True)


def seed_demo(repo: Repository) -> None:
    """Preenche o banco de demonstração na primeira execução."""
    if repo.list_channels():
        return
    channel_ids = {
        channel["youtube_id"]: repo.add_channel(channel["youtube_id"], channel["name"])
        for channel in DEMO_CHANNELS
    }
    first_video_id = None
    for video in DEMO_VIDEOS:
        if not video["initial"]:
            continue
        video_id = repo.add_video(
            channel_ids[video["channel"]], video["youtube_id"], video["title"],
            video["published_at"], video["duration_s"],
        )
        if first_video_id is None:
            first_video_id = video_id
            repo.add_curiosities(video_id, parse_curiosities(video["curiosities"]))

    # Um vídeo já produzido, para o histórico e as telas finais não começarem vazios.
    writer = DemoWriter(delay=0)
    quiet = (lambda percent, label: None, lambda: False)
    used = [row for row in repo.list_curiosities() if row["video_id"] == first_video_id][:2]
    draft = writer.write(to_inputs(used), 60, *quiet)
    script_id = repo.create_script(draft.title, draft.blocks)
    for block in repo.list_blocks(script_id):
        duration = estimate_duration(block["text"])
        repo.update_block(block["id"], media_path=DEMO_MEDIA, duration_s=duration, trim_end=duration)
    repo.update_script(script_id, status="aprovado", render_path=DEMO_RENDER)
    sources = to_sources(repo.script_sources(script_id))
    text = "\n".join(block.text for block in draft.blocks)
    for copy in writer.platform_copy(draft.title, text, sources, *quiet):
        repo.upsert_publication(script_id, copy.platform, copy.title, copy.description, copy.hashtags)
    states = {"youtube": "publicado", "instagram": "agendado", "tiktok": "rascunho"}
    for publication in repo.list_publications(script_id):
        repo.update_publication(publication["id"], status=states[publication["platform"]])
    repo.add_usage("youtube", 3)
    repo.add_usage("gemini", 1)
    repo.add_usage("claude", 2)


def build_context(
    demo: bool = True, delay: float | None = None, credentials: CredentialStore | None = None
) -> AppContext:
    """Monta o contexto do modo escolhido.

    Cada modo tem o seu banco: os dados fictícios nunca se misturam aos reais.
    """
    store = credentials or CredentialStore()
    if demo:
        repo = Repository(data_dir() / "demo.sqlite3")
        seed_demo(repo)
        return AppContext(repo, store, demo_services(delay), demo=True)
    repo = Repository(data_dir() / "trinca.sqlite3")
    models = {
        "gemini": repo.get_setting("gemini_model"),
        "claude": repo.get_setting("claude_model"),
        "writer": repo.get_setting("writer_provider"),
    }
    return AppContext(repo, store, real_services(store, models, delay), demo=False, models=models)
