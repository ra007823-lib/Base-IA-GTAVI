"""Download do vídeo completo de origem, só para canais com autorização registrada.

O vídeo vai para a pasta de saída (até 1080p) e é reaproveitado se já existir, então vários
cortes do mesmo vídeo baixam uma vez só. A tela só chama isto depois que o usuário registra
a autorização do canal (db.set_channel_permission).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

from ..security import ensure_within, validate_video_id, video_url
from .assembly import DEMO_MEDIA
from .contracts import Cancelled, IsCancelled, Progress, ServiceError, simulate
from .media import ffmpeg_dir

log = logging.getLogger(__name__)

MAX_SOURCE_S = 3 * 60 * 60  # recusa vídeos com mais de 3 horas


class SourceDownloader(Protocol):
    def fetch(
        self, video_id: str, dest: Path, progress: Progress, cancelled: IsCancelled
    ) -> str: ...


class DemoDownloader:
    def __init__(self, delay: float = 0.4) -> None:
        self._delay = delay

    def fetch(
        self, video_id: str, dest: Path, progress: Progress, cancelled: IsCancelled
    ) -> str:
        simulate(["Baixando o vídeo"], progress, cancelled, self._delay)
        return DEMO_MEDIA


class YtDlpDownloader:
    def fetch(
        self, video_id: str, dest: Path, progress: Progress, cancelled: IsCancelled
    ) -> str:
        url = video_url(validate_video_id(video_id))
        try:
            import yt_dlp
            from yt_dlp.utils import DownloadCancelled
        except ImportError as exc:
            raise ServiceError("O yt-dlp não está instalado. Rode: pip install yt-dlp") from exc

        dest.parent.mkdir(parents=True, exist_ok=True)
        target = ensure_within(dest.parent, dest)
        if target.is_file() and target.stat().st_size > 0:
            progress(100, "Vídeo já baixado")
            return str(target)
        ffmpeg_folder = ffmpeg_dir()
        if ffmpeg_folder not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = ffmpeg_folder + os.pathsep + os.environ.get("PATH", "")

        def hook(info: dict) -> None:
            if cancelled():
                raise DownloadCancelled()
            total = info.get("total_bytes") or info.get("total_bytes_estimate") or 0
            if total and info.get("status") == "downloading":
                progress(min(int(95 * info.get("downloaded_bytes", 0) / total), 95),
                         "Baixando o vídeo")

        options = {
            "quiet": True, "noprogress": True, "no_warnings": True, "noplaylist": True,
            "socket_timeout": 20, "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4", "ffmpeg_location": ffmpeg_folder,
            "outtmpl": str(target.with_suffix("")) + ".%(ext)s", "overwrites": True,
            "match_filter": _too_long, "progress_hooks": [hook],
        }
        progress(3, "Conectando ao YouTube")
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except DownloadCancelled:
            raise Cancelled() from None
        except Exception as exc:  # noqa: BLE001
            if cancelled():
                raise Cancelled() from None
            log.warning("Falha no download: %s", type(exc).__name__)
            raise ServiceError(
                "Não consegui baixar o vídeo. Ele pode estar privado, com restrição de idade, "
                "ao vivo ou bloqueado. Se persistir, rode: pip install -U yt-dlp"
            ) from exc
        if not target.is_file():
            raise ServiceError(
                "O vídeo é muito longo (limite de 3 horas) ou o arquivo não apareceu."
            )
        progress(100, "Concluído")
        return str(target)


def _too_long(info: dict, *, incomplete: bool = False) -> str | None:
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > MAX_SOURCE_S:
        return "vídeo longo demais"
    return None
