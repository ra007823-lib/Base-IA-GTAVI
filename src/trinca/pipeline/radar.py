"""Radar: encontra vídeos por tema livre ou nos canais monitorados.

A implementação real usa a YouTube Data API. Ler os envios de um canal custa
1 unidade de cota e buscar por tema custa 100. Quando há vídeo novo, mais 1
unidade busca duração, canal e estado dos vídeos.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..config import SEARCH_COST_UNITS, SEARCH_LANGUAGE, SEARCH_PAGE_SIZE, SEARCH_REGION
from ..demo_data import DEMO_CHANNELS, DEMO_VIDEOS
from ..security import (
    ValidationError, clean_text, clean_theme, parse_channel_ref, parse_iso8601_duration,
    validate_channel_id, validate_playlist_id, validate_video_id,
)
from .contracts import (
    ChannelInfo, ChannelRef, DetectedVideo, IsCancelled, Progress, RadarResult, SearchOptions,
    ServiceError, simulate,
)
from .youtube_api import YouTubeApi

log = logging.getLogger(__name__)

UPLOADS_PAGE_SIZE = 10
_ORDERS = frozenset({"relevance", "date", "viewCount"})
_DURATIONS = frozenset({"any", "short", "medium", "long"})
_PERIODS = frozenset({0, 1, 7, 30, 365})


class RadarSource(Protocol):
    def resolve(
        self, reference: str, progress: Progress, cancelled: IsCancelled
    ) -> tuple[ChannelInfo, int]: ...

    def check(
        self, channel: ChannelRef, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult: ...

    def search(
        self, theme: str, options: SearchOptions, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult: ...


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _items(data: dict) -> list[dict]:
    items = data.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _local_time(value: object) -> str:
    """Converte a data do YouTube (UTC) para o horário local, sem fuso."""
    if not isinstance(value, str):
        raise ValidationError("Data de publicação ausente.")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("Data de publicação inválida.") from exc
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.isoformat(timespec="seconds")


class YouTubeRadar:
    def __init__(self, api: YouTubeApi) -> None:
        self._api = api

    def resolve(
        self, reference: str, progress: Progress, cancelled: IsCancelled
    ) -> tuple[ChannelInfo, int]:
        """Busca nome, ID e lista de envios de um canal. Custa 1 unidade."""
        kind, value = parse_channel_ref(reference)
        progress(30, "Buscando o canal no YouTube")
        params = {"part": "snippet,contentDetails", "maxResults": "1"}
        params["id" if kind == "id" else "forHandle"] = value
        items = _items(self._api.get("channels", params))
        if not items:
            raise ServiceError("Canal não encontrado no YouTube.")
        item = items[0]
        uploads = _as_dict(_as_dict(item.get("contentDetails")).get("relatedPlaylists"))
        try:
            info = ChannelInfo(
                youtube_id=validate_channel_id(item.get("id")),
                name=clean_text(_as_dict(item.get("snippet")).get("title"), 80, required=True),
                uploads_playlist=validate_playlist_id(uploads.get("uploads")),
            )
        except ValidationError as exc:
            raise ServiceError("O YouTube devolveu dados inesperados para este canal.") from exc
        return info, 1

    def check(
        self, channel: ChannelRef, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult:
        units = 0
        playlist = channel.uploads_playlist
        if not playlist:
            info, units = self.resolve(channel.youtube_id, progress, cancelled)
            playlist = info.uploads_playlist
        progress(40, "Lendo a lista de envios do canal")
        listing = self._api.get(
            "playlistItems",
            {"part": "contentDetails", "playlistId": validate_playlist_id(playlist),
             "maxResults": str(UPLOADS_PAGE_SIZE)},
        )
        units += 1
        new_ids: list[str] = []
        for item in _items(listing):
            try:
                video_id = validate_video_id(_as_dict(item.get("contentDetails")).get("videoId"))
            except ValidationError:
                continue
            if video_id not in known_ids and video_id not in new_ids:
                new_ids.append(video_id)
        if not new_ids:
            return RadarResult((), units)

        progress(70, "Buscando os detalhes dos vídeos novos")
        return RadarResult(self._details(new_ids), units + 1)

    def search(
        self, theme: str, options: SearchOptions, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult:
        """Busca vídeos sobre um tema livre. Custa 100 unidades, mais 1 se achar vídeo novo."""
        if (
            options.order not in _ORDERS
            or options.duration not in _DURATIONS
            or options.period_days not in _PERIODS
        ):
            raise ValidationError("Opção de busca inválida.")
        params = {
            "part": "snippet", "type": "video", "q": clean_theme(theme),
            "maxResults": str(SEARCH_PAGE_SIZE), "order": options.order,
            "videoDuration": options.duration, "regionCode": SEARCH_REGION,
            "relevanceLanguage": SEARCH_LANGUAGE, "safeSearch": "moderate",
        }
        if options.period_days:
            since = datetime.now(timezone.utc) - timedelta(days=options.period_days)
            params["publishedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        progress(30, "Buscando vídeos sobre o tema no YouTube")
        new_ids: list[str] = []
        for item in _items(self._api.get("search", params)):
            try:
                video_id = validate_video_id(_as_dict(item.get("id")).get("videoId"))
            except ValidationError:
                continue
            if video_id not in known_ids and video_id not in new_ids:
                new_ids.append(video_id)
        if not new_ids:
            return RadarResult((), SEARCH_COST_UNITS)
        progress(70, "Buscando os detalhes dos vídeos encontrados")
        return RadarResult(self._details(new_ids), SEARCH_COST_UNITS + 1)

    def _details(self, video_ids: list[str]) -> tuple[DetectedVideo, ...]:
        """Título, canal, data e duração dos vídeos pedidos. Custa 1 unidade."""
        details = self._api.get(
            "videos", {"part": "snippet,contentDetails", "id": ",".join(video_ids)}
        )
        videos = []
        for item in _items(details):
            snippet = _as_dict(item.get("snippet"))
            duration = parse_iso8601_duration(_as_dict(item.get("contentDetails")).get("duration"))
            # Transmissões ao vivo ou agendadas ficam para a próxima verificação.
            if snippet.get("liveBroadcastContent") != "none" or duration <= 0:
                continue
            try:
                video_id = validate_video_id(item.get("id"))
                if video_id not in video_ids:
                    continue
                videos.append(
                    DetectedVideo(
                        youtube_id=video_id,
                        title=clean_text(snippet.get("title"), 200, required=True),
                        published_at=_local_time(snippet.get("publishedAt")),
                        duration_s=duration,
                        channel_youtube_id=validate_channel_id(snippet.get("channelId")),
                        channel_name=clean_text(snippet.get("channelTitle"), 80, required=True),
                    )
                )
            except ValidationError:
                log.warning("Vídeo ignorado: o YouTube devolveu dados inesperados.")
        return tuple(videos)


class DemoRadar:
    """Entrega um vídeo fictício novo por verificação, até a lista acabar."""

    def __init__(self, delay: float = 0.4) -> None:
        self._delay = delay

    def resolve(
        self, reference: str, progress: Progress, cancelled: IsCancelled
    ) -> tuple[ChannelInfo, int]:
        kind, value = parse_channel_ref(reference)
        if kind != "id":
            raise ValidationError("No modo de demonstração, informe o ID do canal (UC…).")
        simulate(["Buscando o canal"], progress, cancelled, self._delay)
        return ChannelInfo(value, f"Canal de demonstração {value[-4:]}", ""), 0

    def check(
        self, channel: ChannelRef, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult:
        simulate(["Lendo a lista de envios do canal"], progress, cancelled, self._delay)
        for video in DEMO_VIDEOS:
            if video["channel"] == channel.youtube_id and video["youtube_id"] not in known_ids:
                return RadarResult((self._found(video),), 1)
        return RadarResult((), 1)

    def search(
        self, theme: str, options: SearchOptions, known_ids: set[str], progress: Progress,
        cancelled: IsCancelled,
    ) -> RadarResult:
        """Devolve até dois vídeos de exemplo ainda não vistos, qualquer que seja o tema."""
        clean_theme(theme)
        simulate(["Buscando vídeos sobre o tema"], progress, cancelled, self._delay)
        found = [self._found(v) for v in DEMO_VIDEOS if v["youtube_id"] not in known_ids][:2]
        return RadarResult(tuple(found), SEARCH_COST_UNITS + (1 if found else 0))

    @staticmethod
    def _found(video: dict) -> DetectedVideo:
        names = {channel["youtube_id"]: channel["name"] for channel in DEMO_CHANNELS}
        return DetectedVideo(
            video["youtube_id"], video["title"], video["published_at"], video["duration_s"],
            video["channel"], names[video["channel"]],
        )
