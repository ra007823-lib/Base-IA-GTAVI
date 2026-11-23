"""Tipos trocados entre as etapas e validação das respostas das IAs.

As respostas das IAs são tratadas como dados não confiáveis: um vídeo pode
conter texto escrito para manipular o modelo. Por isso cada resposta passa
por uma validação estrita antes de entrar no banco, os links são removidos
e nenhum campo é executado ou usado como caminho de arquivo.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from ..config import PLATFORMS
from ..security import ValidationError, clean_text, strip_urls

Progress = Callable[[int, str], None]
IsCancelled = Callable[[], bool]

MAX_CURIOSITIES = 100
MAX_BLOCKS = MAX_CURIOSITIES
MAX_HASHTAGS = 8
MAX_VIDEO_SECONDS = 12 * 60 * 60


class Cancelled(Exception):
    """A tarefa foi cancelada pelo usuário."""


class ServiceError(Exception):
    """Falha em um serviço externo. A mensagem pode ser mostrada ao usuário."""


@dataclass(frozen=True)
class ChannelInfo:
    youtube_id: str
    name: str
    uploads_playlist: str


@dataclass(frozen=True)
class ChannelRef:
    youtube_id: str
    uploads_playlist: str


@dataclass(frozen=True)
class DetectedVideo:
    youtube_id: str
    title: str
    published_at: str
    duration_s: int = 0
    channel_youtube_id: str = ""
    channel_name: str = ""


@dataclass(frozen=True)
class SearchOptions:
    order: str = "relevance"  # relevance | date | viewCount
    period_days: int = 0  # 0 = qualquer data
    duration: str = "any"  # any | short | medium | long


@dataclass(frozen=True)
class RadarResult:
    videos: tuple[DetectedVideo, ...]
    units: int  # unidades de cota da YouTube Data API gastas


@dataclass(frozen=True)
class CuriosityDraft:
    start_s: float
    end_s: float
    title: str
    description: str
    scene_hint: str
    hook_text: str = ""  # gancho falado de 3 a 5 s que abre o vídeo
    hotspot_s: float = -1.0  # instante do ponto alto no vídeo de origem (-1 = não informado)


@dataclass(frozen=True)
class AnalysisResult:
    drafts: tuple[CuriosityDraft, ...]
    requests: int
    video_seconds: int


@dataclass(frozen=True)
class CuriosityInput:
    id: int
    title: str
    description: str
    scene_hint: str
    channel: str
    video_youtube_id: str
    start_s: float
    theme: str = ""


@dataclass(frozen=True)
class BlockDraft:
    curiosity_id: int | None
    text: str
    scene_hint: str


@dataclass(frozen=True)
class ScriptDraft:
    title: str
    blocks: tuple[BlockDraft, ...]


@dataclass(frozen=True)
class Source:
    channel: str
    video_youtube_id: str
    video_title: str


@dataclass(frozen=True)
class PlatformCopy:
    platform: str
    title: str
    description: str
    hashtags: str


@dataclass(frozen=True)
class BlockTiming:
    block_id: int
    duration_s: float
    caption: str


@dataclass(frozen=True)
class RenderBlock:
    block_id: int
    media_path: str
    trim_start: float
    trim_end: float
    caption: str
    audio_offset_s: float  # início do bloco dentro da narração própria (soma dos anteriores)
    hook_text: str = ""  # gancho falado antes do corte (só no modo de áudio original)
    hotspot_s: float = -1.0  # instante do ponto alto no arquivo de vídeo, para o quadro congelado


@dataclass(frozen=True)
class RenderJob:
    script_id: int
    title: str
    blocks: tuple[RenderBlock, ...]
    narration_mode: str  # propria | sintetica | original (corte com o áudio do vídeo)
    narration_path: str
    caption_style: str
    output_dir: str


def _ai_text(value: object, max_len: int, *, required: bool = False) -> str:
    """Texto vindo de uma IA: sem caracteres de controle e sem links."""
    text = strip_urls(clean_text(value, max_len))
    if required and not text:
        raise ValidationError("A IA devolveu um texto vazio.")
    return text


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"O campo {field} precisa ser um número.")
    return float(value)


HOOK_MAX_WORDS = 16  # cabe em 7 s de voz (cerca de 2,6 palavras por segundo)


def default_hook(*texts: str) -> str:
    """Gancho padrão: o primeiro texto não vazio (do roteiro ou da curiosidade), até 16 palavras.

    Corta no fim de uma frase quando possível, para a voz não parar no meio.
    """
    for text in texts:
        words = (text or "").split()
        if not words:
            continue
        chunk = " ".join(words[:HOOK_MAX_WORDS])
        cut = max(chunk.rfind("."), chunk.rfind("!"), chunk.rfind("?"))
        if len(words) > HOOK_MAX_WORDS and cut > len(chunk) // 2:
            chunk = chunk[: cut + 1]
        return chunk
    return ""


def _hotspot(value: object, start: float, end: float) -> float:
    """Ponto alto dentro do momento; sem valor válido, usa o meio dele."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        if start <= value <= end:
            return float(value)
    return round((start + end) / 2, 2)


def parse_curiosity(item: object) -> CuriosityDraft:
    """Valida uma curiosidade devolvida pelo analista."""
    if not isinstance(item, dict):
        raise ValidationError("Curiosidade em formato inesperado.")
    start = _number(item.get("start_s"), "start_s")
    end = _number(item.get("end_s"), "end_s")
    if not 0 <= start < end <= MAX_VIDEO_SECONDS:
        raise ValidationError("Curiosidade com tempos fora do intervalo válido.")
    return CuriosityDraft(
        start_s=start,
        end_s=end,
        title=_ai_text(item.get("title"), 120, required=True),
        description=_ai_text(item.get("description"), 600, required=True),
        scene_hint=_ai_text(item.get("scene_hint", ""), 300),
        hook_text=_ai_text(item.get("hook", ""), 140),
        hotspot_s=_hotspot(item.get("hotspot_s"), start, end),
    )


def parse_curiosities(payload: object) -> list[CuriosityDraft]:
    """Valida a lista inteira. Qualquer item inválido rejeita a resposta."""
    if not isinstance(payload, list) or not payload:
        raise ValidationError("A análise não devolveu uma lista de curiosidades.")
    if len(payload) > MAX_CURIOSITIES:
        raise ValidationError("A análise devolveu curiosidades demais.")
    return [parse_curiosity(item) for item in payload]


def parse_script(payload: object, items: Sequence[CuriosityInput]) -> ScriptDraft:
    """Valida o roteiro devolvido pelo roteirista.

    Cada bloco precisa apontar para uma das curiosidades enviadas, sem repetir.
    """
    if not isinstance(payload, dict):
        raise ValidationError("O roteiro veio em formato inesperado.")
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list) or not 1 <= len(raw_blocks) <= MAX_BLOCKS:
        raise ValidationError(f"O roteiro precisa ter entre 1 e {MAX_BLOCKS} blocos.")
    by_id = {item.id: item for item in items}
    seen: set[int] = set()
    blocks = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            raise ValidationError("Bloco de roteiro em formato inesperado.")
        curiosity_id = raw.get("curiosity_id")
        if isinstance(curiosity_id, bool) or curiosity_id not in by_id or curiosity_id in seen:
            raise ValidationError("O roteiro cita uma curiosidade que não foi enviada.")
        seen.add(curiosity_id)
        blocks.append(
            BlockDraft(
                curiosity_id=curiosity_id,
                text=_ai_text(raw.get("text"), 700, required=True),
                scene_hint=by_id[curiosity_id].scene_hint,
            )
        )
    return ScriptDraft(
        title=_ai_text(payload.get("title"), 100, required=True), blocks=tuple(blocks)
    )


def parse_platform_copy(payload: object, credit: str) -> list[PlatformCopy]:
    """Valida os textos de publicação e acrescenta o crédito, que é montado pelo app."""
    if not isinstance(payload, dict):
        raise ValidationError("Os textos de publicação vieram em formato inesperado.")
    copies = []
    for platform in PLATFORMS:
        entry = payload.get(platform)
        if not isinstance(entry, dict):
            raise ValidationError("Faltam os textos de uma das plataformas.")
        raw_tags = entry.get("hashtags")
        if not isinstance(raw_tags, list):
            raise ValidationError("As hashtags vieram em formato inesperado.")
        tags: list[str] = []
        for raw in raw_tags:
            word = re.sub(r"\W", "", raw) if isinstance(raw, str) else ""
            tag = f"#{word[:40]}"
            if word and tag not in tags and len(tags) < MAX_HASHTAGS:
                tags.append(tag)
        description = _ai_text(entry.get("description"), 1500, required=True)
        copies.append(
            PlatformCopy(
                platform=platform,
                title=_ai_text(entry.get("title"), 100, required=True),
                description=f"{description}\n\n{credit}" if credit else description,
                hashtags=" ".join(tags),
            )
        )
    return copies


def simulate(
    steps: Sequence[str], progress: Progress, cancelled: IsCancelled, delay: float
) -> None:
    """Percorre as etapas de uma tarefa de demonstração, com pausa e cancelamento."""
    total = len(steps)
    for index, label in enumerate(steps):
        progress(int(index * 100 / total), label)
        waited = 0.0
        while waited < delay:
            if cancelled():
                raise Cancelled()
            time.sleep(0.05)
            waited += 0.05
        if cancelled():
            raise Cancelled()
    progress(100, "Concluído")
