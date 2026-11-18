"""Ferramentas de mídia: localizar o FFmpeg, medir duração e gerar legendas ASS.

O FFmpeg é sempre chamado com lista de argumentos, sem shell, e só com
caminhos absolutos. Se o sistema não tiver FFmpeg, usa o binário que acompanha
o pacote imageio-ffmpeg.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Sequence

from ..config import data_dir
from ..security import ensure_within, safe_slug
from .contracts import Cancelled, IsCancelled, ServiceError

_DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
FFMPEG_TIMEOUT_S = 15 * 60


def ffmpeg_path() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(
            "O FFmpeg não foi encontrado. Instale com: sudo apt install ffmpeg "
            "(ou pip install imageio-ffmpeg)."
        ) from exc


def ffmpeg_dir() -> str:
    """Pasta com um executável chamado 'ffmpeg', no formato que o yt-dlp exige."""
    exe = Path(ffmpeg_path())
    if exe.name == "ffmpeg":
        return str(exe.parent)
    folder = data_dir() / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    link = folder / "ffmpeg"
    if link.is_symlink() and link.resolve() != exe.resolve():
        link.unlink()
    if not link.exists():
        link.symlink_to(exe)
    return str(folder)


def run_ffmpeg(args: Sequence[str], cancelled: IsCancelled, cwd: Path | None = None) -> str:
    """Roda o FFmpeg, respeitando o cancelamento. Devolve o texto de erro (stderr)."""
    if cancelled():
        raise Cancelled()
    process = subprocess.Popen(  # noqa: S603 - lista de argumentos, sem shell
        [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", *args],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, cwd=cwd,
    )
    deadline = time.monotonic() + FFMPEG_TIMEOUT_S
    try:
        while True:
            try:
                _, stderr = process.communicate(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                if cancelled():
                    raise Cancelled() from None
                if time.monotonic() > deadline:
                    raise ServiceError("O FFmpeg demorou demais e foi interrompido.") from None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    if process.returncode != 0:
        tail = " ".join((stderr or "").strip().splitlines()[-2:])
        raise ServiceError(f"O FFmpeg falhou: {tail[:300]}")
    return stderr or ""


def probe_duration(path: Path) -> float:
    """Duração de um arquivo de áudio ou vídeo, em segundos."""
    result = subprocess.run(  # noqa: S603
        [ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    match = _DURATION_RE.search(result.stderr)
    if match is None:
        raise ServiceError(f"Não consegui ler a duração de {path.name}.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def cut_range(start: float, end: float, total: float, low: float, high: float) -> tuple[float, float]:
    """Ajusta o corte (início, fim) para durar entre `low` e `high` segundos dentro do vídeo."""
    start = min(max(start, 0.0), max(total - 1.0, 0.0))
    end = min(max(end, start + 1.0), total)
    if end - start > high:
        end = start + high
    if end - start < low:
        end = min(start + low, total)
        start = max(end - low, 0.0) if end - start < low else start
    return round(start, 2), round(end, 2)


def script_dir(output_dir: Path, script_id: int, title: str) -> Path:
    """Pasta de trabalho de um roteiro, dentro da pasta de saída."""
    base = output_dir.expanduser().resolve()
    folder = ensure_within(base, base / "videos" / f"{script_id:04d}-{safe_slug(title)}")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def block_audio_path(folder: Path, block_id: int) -> Path:
    return folder / "narracao" / f"bloco-{block_id}.mp3"


# ----- legendas -----

# Cores ASS são &HAABBGGRR. Estilo: (fonte, tamanho, cor, contorno, espessura, sombra)
CAPTION_STYLES = {
    "Neon": ("DejaVu Sans", 78, "&H0000FFFF", "&H00FF00FF", 5, 0),
    "Clássico": ("DejaVu Sans", 72, "&H00FFFFFF", "&H00000000", 5, 1),
    "Minimalista": ("DejaVu Sans", 60, "&H00FFFFFF", "&H00000000", 0, 3),
}


def split_caption(text: str, max_words: int = 3) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def _stamp(seconds: float) -> str:
    centis = int(round(seconds * 100))
    return f"{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}"


def build_ass(text: str, duration_s: float, style_name: str) -> str:
    """Legenda ASS 1080x1920 com o texto dividido em trechos curtos, no tempo do bloco."""
    font, size, color, outline_color, outline, shadow = CAPTION_STYLES.get(
        style_name, CAPTION_STYLES["Neon"]
    )
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,"
        "Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{size},{color},{color},{outline_color},&H80000000,-1,0,0,0,"
        f"100,100,0,0,1,{outline},{shadow},2,60,60,420,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    chunks = split_caption(text) or [""]
    weights = [max(len(chunk), 1) for chunk in chunks]
    total, cursor, lines = sum(weights), 0.0, []
    for chunk, weight in zip(chunks, weights):
        end = cursor + duration_s * weight / total
        safe = chunk.replace("\\", "").replace("{", "(").replace("}", ")")
        lines.append(
            f"Dialogue: 0,{_stamp(cursor)},{_stamp(end)},Default,,0,0,0,,{safe}"
        )
        cursor = end
    return header + "\n".join(lines) + "\n"
