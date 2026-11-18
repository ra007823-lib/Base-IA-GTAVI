"""Publicação: YouTube pelo navegador (youtube_browser.py) e pacote manual para Instagram e TikTok.

Para Instagram e TikTok o app monta uma pasta com tudo pronto e abre a página
oficial de upload.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from ..config import PLATFORM_LABELS, PLATFORMS
from ..security import ValidationError, ensure_within, safe_slug
from .contracts import IsCancelled, PlatformCopy, Progress, simulate


class Publisher(Protocol):
    def schedule(
        self, copy: PlatformCopy, render_path: str, scheduled_at: str, progress: Progress,
        cancelled: IsCancelled,
    ) -> str: ...


class DemoYouTube:
    """Simula o agendamento. Nada é enviado ao YouTube."""

    def __init__(self, delay: float = 0.4) -> None:
        self._delay = delay

    def schedule(
        self, copy: PlatformCopy, render_path: str, scheduled_at: str, progress: Progress,
        cancelled: IsCancelled,
    ) -> str:
        simulate(["Enviando o vídeo", "Agendando a publicação"], progress, cancelled, self._delay)
        return ""  # a versão real (BrowserYouTube) devolve o link do vídeo


def build_package(
    output_dir: Path, script_id: int, script_title: str, copy: PlatformCopy,
    scheduled_at: str, render_path: str,
) -> Path:
    """Cria a pasta de publicação de um vídeo para uma plataforma."""
    if copy.platform not in PLATFORMS:
        raise ValidationError("Plataforma desconhecida.")
    base = output_dir.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    folder = ensure_within(
        base, base / f"{script_id:04d}-{safe_slug(script_title)}" / copy.platform
    )
    folder.mkdir(parents=True, exist_ok=True)

    lines = [
        f"Plataforma: {PLATFORM_LABELS[copy.platform]}",
        f"Horário sugerido: {scheduled_at or 'a definir'}",
        "",
        "TÍTULO",
        copy.title,
        "",
        "DESCRIÇÃO",
        copy.description,
        "",
        "HASHTAGS",
        copy.hashtags,
        "",
    ]
    (folder / "legenda.txt").write_text("\n".join(lines), encoding="utf-8")

    video = Path(render_path)
    if render_path and video.is_absolute() and video.is_file():
        shutil.copy2(video, folder / f"video{video.suffix.lower()}")
    return folder
