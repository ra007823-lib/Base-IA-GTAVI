"""Validação de entradas e proteção de segredos.

Tudo o que vem de fora do app passa por aqui antes de ser usado: texto
digitado, respostas das IAs, identificadores do YouTube, URLs e caminhos.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{3,30}$")
PLAYLIST_ID_RE = re.compile(r"^UU[A-Za-z0-9_-]{22}$")
MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,63}$")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_YOUTUBE_HOSTS = frozenset({"www.youtube.com", "youtube.com", "m.youtube.com"})

# Únicos destinos que o app abre no navegador.
ALLOWED_HOSTS = frozenset(
    {
        "www.youtube.com",
        "youtube.com",
        "youtu.be",
        "studio.youtube.com",
        "www.instagram.com",
        "www.tiktok.com",
    }
)

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm"})
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".ogg", ".flac"})

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),  # chaves do Google
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # chaves no formato sk-...
    re.compile(r"ya29\.[0-9A-Za-z._-]{20,}"),  # tokens OAuth do Google
)
_SECRET_PARAM = re.compile(r"(?i)\b(key|token|secret|password|authorization)(\s*[=:]\s*)(\S+)")


class ValidationError(ValueError):
    """Entrada rejeitada. A mensagem pode ser mostrada ao usuário."""


def clean_text(value: object, max_len: int, *, required: bool = False) -> str:
    """Remove caracteres de controle, apara e limita o tamanho de um texto."""
    if not isinstance(value, str):
        raise ValidationError("Era esperado um texto.")
    kept = "".join(
        ch for ch in value if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )
    text = kept.strip()[:max_len]
    if required and not text:
        raise ValidationError("O texto não pode ficar vazio.")
    return text


def validate_channel_id(value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not CHANNEL_ID_RE.fullmatch(text):
        raise ValidationError(
            "ID de canal inválido. Ele começa com UC e tem 24 caracteres."
        )
    return text


def validate_video_id(value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not VIDEO_ID_RE.fullmatch(text):
        raise ValidationError("ID de vídeo inválido.")
    return text


def validate_playlist_id(value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not PLAYLIST_ID_RE.fullmatch(text):
        raise ValidationError("Lista de envios do canal em formato inesperado.")
    return text


def validate_model_name(value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not MODEL_NAME_RE.fullmatch(text):
        raise ValidationError("Nome de modelo inválido. Use o ID exato, como gemini-4-hydrogen.")
    return text


def clean_theme(value: object) -> str:
    """Tema de busca digitado pelo usuário: uma linha curta, sem marcações."""
    text = re.sub(r"[«»<>{}\[\]\s]+", " ", clean_text(value, 200)).strip()[:80].strip()
    if len(text) < 2:
        raise ValidationError("Digite um tema com pelo menos 2 caracteres.")
    return text


def parse_channel_ref(value: object) -> tuple[str, str]:
    """Aceita o ID (UC…), o @ do canal ou o link dele. Devolve ('id' | 'handle', valor)."""
    text = value.strip() if isinstance(value, str) else ""
    if text.startswith(("https://", "http://")):
        try:
            parts = urlsplit(text)
        except ValueError:
            parts = None
        segments = [s for s in parts.path.split("/") if s] if parts else []
        if parts is None or parts.hostname not in _YOUTUBE_HOSTS or not segments:
            raise ValidationError("O link não é de um canal do YouTube.")
        text = segments[1] if segments[0] == "channel" and len(segments) > 1 else segments[0]
    if CHANNEL_ID_RE.fullmatch(text):
        return "id", text
    if HANDLE_RE.fullmatch(text):
        return "handle", text
    raise ValidationError("Informe o ID do canal (UC…), o @ do canal ou o link dele.")


def parse_iso8601_duration(value: object) -> int:
    """Duração do YouTube (ex.: PT1H2M3S) em segundos. Devolve 0 se for inválida."""
    match = _DURATION_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return 0
    days, hours, minutes, seconds = (int(group or 0) for group in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_timestamp(value: object) -> float:
    """Converte MM:SS, H:MM:SS ou um número de segundos em segundos."""
    if isinstance(value, bool):
        raise ValidationError("Tempo em formato inesperado.")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str) and re.fullmatch(r"\d{1,4}(:\d{1,2}){1,2}", value.strip()):
        seconds = 0.0
        for part in value.strip().split(":"):
            seconds = seconds * 60 + int(part)
    else:
        raise ValidationError("Tempo em formato inesperado.")
    if not 0 <= seconds < 24 * 3600:
        raise ValidationError("Tempo fora do intervalo válido.")
    return seconds


def strip_urls(text: str) -> str:
    """Remove links de um texto gerado por IA.

    Os únicos links que o app publica são os de crédito, montados por ele mesmo.
    Isso impede que um vídeo de terceiros consiga plantar um link na descrição.
    """
    return re.sub(r"[ \t]{2,}", " ", _URL_RE.sub("", text)).strip()


def video_url(video_id: str, start_s: float | None = None) -> str:
    """Monta o link do vídeo original, opcionalmente no momento indicado."""
    url = f"https://www.youtube.com/watch?v={validate_video_id(video_id)}"
    if start_s is not None and start_s > 0:
        url += f"&t={int(start_s)}s"
    return url


def is_allowed_url(url: object) -> bool:
    """Aceita apenas https para os hosts da lista, sem usuário nem porta."""
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in ALLOWED_HOSTS
        and parts.username is None
        and parts.password is None
        and port is None
    )


def safe_slug(text: str, max_len: int = 48) -> str:
    """Nome de pasta seguro: só letras minúsculas, números e hífens."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:max_len].strip("-")
    return slug or "sem-titulo"


def ensure_within(base: Path, target: Path) -> Path:
    """Garante que o destino fica dentro da pasta base (sem travessia de caminho)."""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if not target_resolved.is_relative_to(base_resolved):
        raise ValidationError("O caminho de destino sai da pasta permitida.")
    return target_resolved


def safe_media_path(path: object, extensions: frozenset[str]) -> Path:
    """Valida um arquivo de mídia local escolhido pelo usuário.

    O caminho devolvido é absoluto. Isso também impede que um nome de arquivo
    iniciado por hífen seja lido como opção pelo FFmpeg.
    """
    if not isinstance(path, (str, Path)) or not str(path):
        raise ValidationError("Nenhum arquivo foi escolhido.")
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError("O arquivo não existe.")
    if resolved.suffix.lower() not in extensions:
        allowed = ", ".join(sorted(extensions))
        raise ValidationError(f"Formato não aceito. Use um destes: {allowed}.")
    if resolved.stat().st_size == 0:
        raise ValidationError("O arquivo está vazio.")
    return resolved


def redact(text: str) -> str:
    """Oculta chaves e tokens de um texto antes de registrá-lo ou exibi-lo."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[oculto]", text)
    return _SECRET_PARAM.sub(lambda m: f"{m.group(1)}{m.group(2)}[oculto]", text)


class RedactingFilter(logging.Filter):
    """Filtro de log que impede o vazamento de segredos."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True
