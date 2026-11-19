"""Constantes e caminhos do aplicativo."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Macaco"
# O ID continua "trinca" (pasta de dados, cofre e pacote) para não perder o que já foi salvo.
APP_ID = "trinca"
KEYRING_SERVICE = "trinca-studio"

PLATFORMS = ("youtube", "instagram", "tiktok")
PLATFORM_LABELS = {
    "youtube": "YouTube Shorts", "instagram": "Instagram Reels", "tiktok": "TikTok",
}

# Páginas oficiais de upload, abertas pelo pacote de publicação.
UPLOAD_PAGES = {
    "youtube": "https://studio.youtube.com/",
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
}

# Duração do vídeo final: de 30 s a 1 min 30 s.
CUT_BUFFER_S = 1.5  # folga antes e depois do trecho da IA, para não cortar no meio da fala
MIN_OUTPUT_S = 30
MAX_OUTPUT_S = 90

YOUTUBE_DAILY_QUOTA = 10_000
# Uma busca por tema custa 100 unidades, mais 1 para os detalhes dos vídeos.
SEARCH_COST_UNITS = 100
SEARCH_PAGE_SIZE = 15
SEARCH_REGION = "BR"
SEARCH_LANGUAGE = "pt"
SEARCH_ORDERS = (("Mais relevantes", "relevance"), ("Mais recentes", "date"),
                 ("Mais vistos", "viewCount"))
SEARCH_PERIODS = (("Qualquer data", 0), ("Últimas 24 horas", 1), ("Última semana", 7),
                  ("Último mês", 30), ("Último ano", 365))
SEARCH_DURATIONS = (("Qualquer duração", "any"), ("Até 4 minutos", "short"),
                    ("De 4 a 20 minutos", "medium"), ("Mais de 20 minutos", "long"))
# No plano gratuito, o Gemini aceita até 8 horas de vídeo do YouTube por dia.
GEMINI_FREE_DAILY_VIDEO_S = 8 * 3600
# Vídeos longos são analisados em partes deste tamanho, uma por pedido.
ANALYSIS_CHUNK_S = 20 * 60

# IDs conferidos na documentação de cada serviço em 16/11/2026.
# Os dois campos aceitam outro ID em Configurações quando os modelos mudarem.
GEMINI_MODELS = ("gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon")
CLAUDE_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")

DEFAULT_SETTINGS = {
    "radar_interval_min": "15",
    "max_duration_s": "90",
    "curiosities_per_video": "3",
    "caption_style": "Neon",
    "speech_provider": "whisper",
    "output_dir": "",
    "gemini_model": GEMINI_MODELS[0],
    "claude_model": CLAUDE_MODELS[0],
    "writer_provider": "gemini",
    "search_order": "relevance",
    "search_period_days": "0",
    "search_duration": "any",
}

# Voz neural em português do Brasil e modelo do Whisper (baixado no primeiro uso).
TTS_VOICE = "pt-BR-AntonioNeural"
WHISPER_MODEL = "base"

CAPTION_STYLES = ("Neon", "Clássico", "Minimalista")
SPEECH_PROVIDERS = {"whisper": "Whisper (padrão)"}


def data_dir() -> Path:
    """Pasta de dados do app, acessível apenas pelo usuário (0700)."""
    override = os.environ.get("TRINCA_DATA_DIR")
    if override:
        base = Path(override)
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    return base


def default_output_dir() -> Path:
    return data_dir() / "saida"


def load_demo_mode() -> bool:
    """Modo escolhido na última execução. O padrão é a demonstração."""
    try:
        return (data_dir() / "modo.txt").read_text(encoding="utf-8").strip() != "real"
    except OSError:
        return True


def save_demo_mode(demo: bool) -> None:
    (data_dir() / "modo.txt").write_text("demo" if demo else "real", encoding="utf-8")
