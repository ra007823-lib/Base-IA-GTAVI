"""Radar sem chave de API: lê buscas e listas de envios públicas do YouTube com o yt-dlp.

Só metadados (título, canal, data, duração). Nenhum vídeo é baixado. Não gasta a
cota da YouTube Data API, então as unidades devolvidas são sempre 0.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from ..config import SEARCH_PAGE_SIZE
from ..security import (
    ValidationError, clean_text, clean_theme, parse_channel_ref, validate_channel_id,
    validate_playlist_id, validate_video_id,
)
from .contracts import (
    Cancelled, ChannelInfo, ChannelRef, DetectedVideo, IsCancelled, Progress, RadarResult,
    SearchOptions, ServiceError,
)

log = logging.getLogger(__name__)

UPLOADS_PAGE_SIZE = 10
_POOL = SEARCH_PAGE_SIZE * 2  # resultados lidos antes de filtrar por duração e data
_ORDERS = frozenset({"relevance", "date", "viewCount", "subscribers"})
_AUDIENCES = frozenset({"br", "any"})
_SIZES = frozenset({0, 100_000, 500_000, 1_000_000})
# Busca como um usuário brasileiro: interface em português e região Brasil.
_BRAZIL = {"extractor_args": {"youtube": {"lang": ["pt"]}}, "geo_bypass_country": "BR"}

_WORD_RE = re.compile(r"[a-zà-ú]+")
_PT_WORDS = frozenset(
    "não nao você voce vocês pra isso essa esse está tá também tambem muito jogo jogando "
    "joguei vamos hoje tudo nada coisas coisa segredo segredos curiosidades melhor melhores "
    "primeira primeiro parte vivo ao que com uma um meu minha nosso novo nova agora ainda "
    "quando onde porque mas mais sobre fiz fui achei descobri olha veja finalmente zerando "
    "zerei episódio dia".split()
)
_OTHER_WORDS = frozenset(
    "the and you your with what how this that is are was in of for my everything new first "
    "full walkthrough commentary game el los las del en sin abierto juego jugando muy pero "
    "también nuevo primera".split()
)


def looks_portuguese(*texts: str) -> bool:
    """Estimativa simples de que o vídeo é em português (título e começo da descrição)."""
    text = " ".join(t or "" for t in texts).lower()
    # Links e domínios (instagram.com, PS5 PRO...) não dizem nada sobre o idioma.
    text = re.sub(r"\S*(https?://|www\.|\.com|\.br)\S*", " ", text)
    words = _WORD_RE.findall(text)
    score = sum(w in _PT_WORDS for w in words) - sum(w in _OTHER_WORDS for w in words)
    score += 2 * len(re.findall(r"[ãõç]", text))
    return score >= 1

_DURATIONS = {"any": (0, 10**9), "short": (1, 240), "medium": (240, 1200), "long": (1200, 10**9)}
_PERIODS = frozenset({0, 1, 7, 30, 365})
_BASE = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20,
         "noplaylist": False}


def _ydl(**extra: Any):  # noqa: ANN202
    try:
        import yt_dlp
    except ImportError as exc:
        raise ServiceError("O yt-dlp não está instalado. Rode: pip install yt-dlp") from exc
    return yt_dlp.YoutubeDL({**_BASE, **extra})


def _extract(url: str, **extra: Any) -> dict:
    try:
        with _ydl(**extra) as ydl:
            info = ydl.extract_info(url, download=False)
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - yt-dlp lança vários tipos de erro
        log.warning("Falha ao ler o YouTube: %s", type(exc).__name__)
        raise ServiceError(
            "Não consegui ler o YouTube agora. Confira a internet e, se persistir, "
            "atualize o yt-dlp (pip install -U yt-dlp)."
        ) from exc
    return info if isinstance(info, dict) else {}


def _entries(info: dict) -> list[dict]:
    entries = info.get("entries")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _moment(info: dict) -> datetime | None:
    stamp = info.get("timestamp")
    if isinstance(stamp, (int, float)):
        return datetime.fromtimestamp(stamp)  # horário local, sem fuso
    date = info.get("upload_date")
    if isinstance(date, str) and len(date) == 8 and date.isdigit():
        try:
            return datetime.strptime(date, "%Y%m%d")
        except ValueError:
            return None
    return None


class YtDlpRadar:
    def resolve(
        self, reference: str, progress: Progress, cancelled: IsCancelled
    ) -> tuple[ChannelInfo, int]:
        kind, value = parse_channel_ref(reference)
        progress(30, "Buscando o canal no YouTube")
        base = (f"https://www.youtube.com/channel/{value}" if kind == "id"
                else f"https://www.youtube.com/@{value.lstrip('@')}")
        try:
            info = _extract(f"{base}/videos", extract_flat=True, playlistend=1)
        except ServiceError:
            # Canal novo ou sem vídeos públicos não tem a aba "Vídeos": lê a página do canal.
            info = _extract(base, extract_flat=True, playlistend=1)
        try:
            channel_id = validate_channel_id(info.get("channel_id") or info.get("id"))
            name = clean_text(info.get("channel") or info.get("uploader"), 80, required=True)
            playlist = validate_playlist_id("UU" + channel_id[2:])
        except ValidationError as exc:
            raise ServiceError("Canal não encontrado no YouTube.") from exc
        return ChannelInfo(channel_id, name, playlist), 0

    def fetch_video(
        self, video_id: str, progress: Progress, cancelled: IsCancelled
    ) -> DetectedVideo:
        """Lê os dados de um vídeo pelo link. Só metadados, nada é baixado."""
        progress(30, "Lendo o vídeo no YouTube")
        found = self._details([validate_video_id(video_id)], cancelled)
        if not found:
            raise ServiceError(
                "Não consegui usar este vídeo: pode ser uma transmissão ao vivo ainda não "
                "encerrada, ou o YouTube não devolveu os dados."
            )
        return found[0]

    def check(
        self, channel: ChannelRef, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult:
        progress(40, "Lendo a lista de envios do canal")
        base = f"https://www.youtube.com/channel/{validate_channel_id(channel.youtube_id)}"
        try:
            info = _extract(f"{base}/videos", extract_flat=True, playlistend=UPLOADS_PAGE_SIZE)
        except ServiceError:
            # Sem a aba "Vídeos" o canal não tem envios públicos. Se a página do canal abre,
            # não há vídeo novo; se nem ela abre, o erro é real (rede ou yt-dlp).
            _extract(base, extract_flat=True, playlistend=1)
            return RadarResult((), 0)
        new_ids = self._new_ids(_entries(info), known_ids)
        if not new_ids:
            return RadarResult((), 0)
        progress(70, "Buscando os detalhes dos vídeos novos")
        return RadarResult(self._details(new_ids, cancelled), 0)

    def search(
        self, theme: str, options: SearchOptions, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult:
        if (
            options.order not in _ORDERS
            or options.duration not in _DURATIONS
            or options.period_days not in _PERIODS
            or options.audience not in _AUDIENCES
            or options.min_subscribers not in _SIZES
        ):
            raise ValidationError("Opção de busca inválida.")
        brazil = options.audience == "br"
        filtered = brazil or options.min_subscribers > 0
        progress(20, "Buscando vídeos sobre o tema no YouTube"
                     + (" (público brasileiro)" if brazil else ""))
        info = _extract(
            f"ytsearch{_POOL * 2 if filtered else _POOL}:{clean_theme(theme)}",
            extract_flat=True, **(_BRAZIL if brazil else {}),
        )
        low, high = _DURATIONS[options.duration]
        candidates = [
            e for e in _entries(info)
            if isinstance(e.get("duration"), (int, float)) and low <= e["duration"] < high
        ]
        views = {e.get("id"): e.get("view_count") or 0 for e in candidates}
        new_ids = self._new_ids(candidates, known_ids)[
            : SEARCH_PAGE_SIZE * 2 if filtered else SEARCH_PAGE_SIZE
        ]
        if not new_ids:
            return RadarResult((), 0)

        def accept(item: dict) -> bool:
            followers = item.get("channel_follower_count")
            followers = followers if isinstance(followers, int) else 0
            if followers < options.min_subscribers:
                return False
            return not brazil or looks_portuguese(
                str(item.get("title") or ""), str(item.get("description") or "")[:400]
            )

        progress(40, "Buscando os detalhes dos vídeos encontrados")
        found = list(self._details(new_ids, cancelled, progress, accept))
        if options.period_days:
            since = datetime.now() - timedelta(days=options.period_days)
            found = [v for v in found if datetime.fromisoformat(v.published_at) >= since]
        if options.order == "date":
            found.sort(key=lambda v: v.published_at, reverse=True)
        elif options.order == "viewCount":
            found.sort(key=lambda v: views.get(v.youtube_id, 0), reverse=True)
        elif options.order == "subscribers":
            found.sort(key=lambda v: v.subscribers, reverse=True)
        return RadarResult(tuple(found[:SEARCH_PAGE_SIZE]), 0)

    @staticmethod
    def _new_ids(entries: list[dict], known_ids: set[str]) -> list[str]:
        ids: list[str] = []
        for entry in entries:
            try:
                video_id = validate_video_id(entry.get("id"))
            except ValidationError:
                continue
            if video_id not in known_ids and video_id not in ids:
                ids.append(video_id)
        return ids

    def _details(
        self, video_ids: list[str], cancelled: IsCancelled, progress: Progress | None = None,
        accept: Callable[[dict], bool] | None = None,
    ) -> tuple[DetectedVideo, ...]:
        videos = []
        for index, video_id in enumerate(video_ids):
            if cancelled():
                raise Cancelled()
            if progress:
                progress(40 + int(55 * index / len(video_ids)),
                         f"Lendo o vídeo {index + 1} de {len(video_ids)}")
            try:
                item = _extract(f"https://www.youtube.com/watch?v={video_id}")
            except ServiceError:
                if index == 0:
                    raise
                continue
            moment, duration = _moment(item), item.get("duration")
            # Transmissões ao vivo ou agendadas ficam para a próxima verificação.
            if (
                item.get("live_status") not in (None, "not_live", "was_live", "post_live", "")
                or moment is None or not isinstance(duration, (int, float)) or duration <= 0
            ):
                continue
            if accept is not None and not accept(item):
                continue
            followers = item.get("channel_follower_count")
            try:
                videos.append(DetectedVideo(
                    youtube_id=validate_video_id(item.get("id")),
                    title=clean_text(item.get("title"), 200, required=True),
                    published_at=moment.isoformat(timespec="seconds"),
                    duration_s=int(duration),
                    channel_youtube_id=validate_channel_id(item.get("channel_id")),
                    channel_name=clean_text(item.get("channel"), 80, required=True),
                    subscribers=followers if isinstance(followers, int) and followers > 0 else 0,
                ))
            except ValidationError:
                log.warning("Vídeo ignorado: o YouTube devolveu dados inesperados.")
        return tuple(videos)
