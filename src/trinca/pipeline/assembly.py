"""Montagem: gera o vídeo final em 9:16 com legendas e narração.

A implementação real chama o FFmpeg com lista de argumentos, sem shell, e só com
caminhos absolutos já validados por security.safe_media_path.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from .contracts import IsCancelled, Progress, RenderBlock, RenderJob, ServiceError, simulate
from .media import (
    block_audio_path, build_ass, cuts_dir, probe_duration, run_ffmpeg, script_dir,
)
from .narration import synthesize_text

DEMO_MEDIA = "demo://midia"
DEMO_RENDER = "demo://render"
WIDTH, HEIGHT, FPS = 1080, 1920, 30
HOOK_MIN_S, HOOK_MAX_S = 3.0, 7.0
# Quadro em 9:16 com o vídeo inteiro sobre um fundo desfocado.
_FIT_GRAPH = (
    f"[0:v]split[a][b];"
    f"[a]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
    f"crop={WIDTH}:{HEIGHT},boxblur=24:6[bg];"
    f"[b]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}"
)


class Assembler(Protocol):
    def render(self, job: RenderJob, progress: Progress, cancelled: IsCancelled) -> str: ...


class DemoAssembler:
    """Simula a renderização. Nenhum arquivo de vídeo é gerado."""

    def __init__(self, delay: float = 0.4) -> None:
        self._delay = delay

    def render(self, job: RenderJob, progress: Progress, cancelled: IsCancelled) -> str:
        simulate(
            ["Cortando os blocos", "Convertendo para vertical 9:16", "Aplicando as legendas",
             "Unindo vídeo e narração"],
            progress, cancelled, self._delay,
        )
        return DEMO_RENDER


class FfmpegAssembler:
    """Corta cada bloco, converte para 9:16, queima a legenda, põe a narração e une tudo."""

    def render(self, job: RenderJob, progress: Progress, cancelled: IsCancelled) -> str:
        if not job.blocks:
            raise ServiceError("O roteiro não tem blocos.")
        folder = script_dir(Path(job.output_dir), job.script_id, job.title)
        parts = []
        total = len(job.blocks)
        for index, block in enumerate(job.blocks):
            progress(int(90 * index / total), f"Montando o bloco {index + 1} de {total}")
            parts.append(self._block(job, block, folder, cancelled))
        progress(92, "Unindo os blocos")
        listing = folder / "partes.txt"
        listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
        final = folder / "video.mp4"
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", listing.name, "-c", "copy",
             "-movflags", "+faststart", final.name],
            cancelled, cwd=folder,
        )
        for part in parts:
            part.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)
        # O vídeo pronto (e a capa) ficam na pasta de cortes, com o nome do roteiro.
        ready = cuts_dir(Path(job.output_dir)) / f"{folder.name}.mp4"
        shutil.move(str(final), ready)
        cover = folder / "capa.jpg"
        if cover.is_file():
            shutil.move(str(cover), ready.with_suffix(".jpg"))
        progress(100, "Concluído")
        return str(ready)

    @staticmethod
    def _cut(args: list[str], out: Path, length: float, folder: Path, cancelled) -> Path:  # noqa: ANN001
        """Corte do vídeo real: mantém o áudio original e o quadro inteiro (fundo desfocado)."""
        graph = f"{_FIT_GRAPH}[v]"
        args += [
            "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", f"{length:.3f}", out.name,
        ]
        run_ffmpeg(args, cancelled, cwd=folder)
        return out

    @staticmethod
    def _with_hook(job, block, media: Path, cut: Path, folder: Path, cancelled) -> Path:  # noqa: ANN001
        """Abre o corte com um gancho falado sobre o quadro do ponto alto congelado.

        O mesmo quadro vira a capa (capa.jpg), que serve como imagem de abertura.
        """
        frame = folder / f"quadro-{block.block_id}.jpg"
        spot = block.hotspot_s
        if not block.trim_start <= spot < block.trim_end:
            # Sem ponto alto válido dentro do corte: usa um instante logo após o começo dele.
            spot = block.trim_start + 0.4 * (block.trim_end - block.trim_start)
        run_ffmpeg(
            ["-ss", f"{spot:.3f}", "-i", str(media), "-frames:v", "1", "-q:v", "2",
             frame.name],
            cancelled, cwd=folder,
        )
        voice = folder / f"gancho-{block.block_id}.mp3"
        synthesize_text(block.hook_text, voice)
        length = min(max(probe_duration(voice) + 0.3, HOOK_MIN_S), HOOK_MAX_S)
        ass = folder / f"gancho-{block.block_id}.ass"
        ass.write_text(build_ass(block.hook_text, length, job.caption_style), encoding="utf-8")
        intro = folder / f"intro-{block.block_id}.mp4"
        graph = f"{_FIT_GRAPH},subtitles={ass.name}[v]"
        run_ffmpeg(
            ["-loop", "1", "-framerate", str(FPS), "-i", frame.name, "-i", voice.name,
             "-filter_complex", graph, "-map", "[v]", "-map", "1:a:0",
             "-af", f"apad,atrim=duration={length:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", f"{length:.3f}", intro.name],
            cancelled, cwd=folder,
        )
        cover = folder / "capa.jpg"
        if not cover.exists() or block.block_id == job.blocks[0].block_id:
            run_ffmpeg(
                ["-i", frame.name, "-filter_complex", f"{_FIT_GRAPH}[v]", "-map", "[v]",
                 "-frames:v", "1", "-q:v", "2", "-y", cover.name],
                cancelled, cwd=folder,
            )
        joined = folder / f"parte-{block.block_id}-gancho.mp4"
        listing = folder / f"gancho-{block.block_id}.txt"
        listing.write_text(f"file '{intro.name}'\nfile '{cut.name}'\n", encoding="utf-8")
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", listing.name, "-c", "copy", joined.name],
            cancelled, cwd=folder,
        )
        for temp in (frame, voice, ass, intro, cut, listing):
            temp.unlink(missing_ok=True)
        return joined

    @staticmethod
    def _block(job: RenderJob, block: RenderBlock, folder: Path, cancelled) -> Path:  # noqa: ANN001
        media = Path(block.media_path)
        if not media.is_absolute() or not media.is_file():
            raise ServiceError(f"O vídeo do bloco não foi encontrado: {media.name or 'vazio'}.")
        length = block.trim_end - block.trim_start
        if length <= 0:
            raise ServiceError("Um bloco ficou sem duração.")
        out = folder / f"parte-{block.block_id}.mp4"
        args = ["-ss", f"{block.trim_start:.3f}", "-t", f"{length:.3f}", "-i", str(media)]
        if job.narration_mode == "original":
            cut = FfmpegAssembler._cut(args, out, length, folder, cancelled)
            if not block.hook_text.strip():
                return cut
            return FfmpegAssembler._with_hook(job, block, media, cut, folder, cancelled)
        ass = folder / f"legenda-{block.block_id}.ass"
        ass.write_text(build_ass(block.caption, length, job.caption_style), encoding="utf-8")
        if job.narration_mode == "sintetica":
            audio = block_audio_path(folder, block.block_id)
            if not audio.is_file():
                raise ServiceError("A narração sintética deste bloco não existe. Gere de novo.")
            args += ["-ss", f"{block.trim_start:.3f}", "-t", f"{length:.3f}", "-i", str(audio)]
        else:
            narration = Path(job.narration_path)
            if not narration.is_absolute() or not narration.is_file():
                raise ServiceError("A narração importada não foi encontrada.")
            start = block.audio_offset_s + block.trim_start
            args += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(narration)]

        video_filter = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS},"
            f"tpad=stop_mode=clone:stop_duration={length:.3f},trim=duration={length:.3f},"
            f"setpts=PTS-STARTPTS,subtitles={ass.name}"
        )
        args += [
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", video_filter, "-af", f"apad,atrim=duration={length:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", f"{length:.3f}", out.name,
        ]
        run_ffmpeg(args, cancelled, cwd=folder)
        ass.unlink(missing_ok=True)
        return out
