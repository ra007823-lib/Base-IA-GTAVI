"""Narração e legendas, atrás de uma interface trocável (SpeechProvider).

LocalSpeech:
- voz sintética: edge-tts (voz neural da Microsoft, sem chave; o texto do bloco vai
  para o serviço) gera um áudio por bloco;
- gravação própria: o Whisper (faster-whisper, local) marca o tempo das palavras e
  o app divide a gravação entre os blocos. Sem o Whisper, divide pelo tamanho do texto.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Protocol, Sequence

from ..config import TTS_VOICE, WHISPER_MODEL
from .contracts import BlockTiming, Cancelled, IsCancelled, Progress, ServiceError, simulate
from .media import block_audio_path, probe_duration, run_ffmpeg

log = logging.getLogger(__name__)

WORDS_PER_SECOND = 2.6


def estimate_duration(text: str) -> float:
    """Duração estimada da narração de um texto, em segundos."""
    return max(3.0, round(len(text.split()) / WORDS_PER_SECOND, 1))


def synthesize_text(text: str, target: Path) -> None:
    """Gera a voz sintética de um texto (edge-tts) em um arquivo de áudio."""
    try:
        import edge_tts
    except ImportError as exc:
        raise ServiceError("O edge-tts não está instalado. Rode: pip install edge-tts") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(edge_tts.Communicate(text, TTS_VOICE).save(str(target)))
    except Exception as exc:  # noqa: BLE001 - rede ou serviço fora do ar
        log.warning("Falha na voz sintética: %s", type(exc).__name__)
        raise ServiceError(
            "Não consegui gerar a voz sintética. Confira a internet ou use a sua gravação."
        ) from exc


class SpeechProvider(Protocol):
    def prepare(
        self, blocks: Sequence[tuple[int, str]], mode: str, progress: Progress,
        cancelled: IsCancelled, narration_path: str = "", work_dir: Path | None = None,
    ) -> list[BlockTiming]: ...


class DemoSpeech:
    def __init__(self, delay: float = 0.4) -> None:
        self._delay = delay

    def prepare(
        self, blocks: Sequence[tuple[int, str]], mode: str, progress: Progress,
        cancelled: IsCancelled, narration_path: str = "", work_dir: Path | None = None,
    ) -> list[BlockTiming]:
        first = "Gerando a narração sintética" if mode == "sintetica" else "Transcrevendo a narração"
        simulate(
            [first, "Sincronizando a narração com os blocos", "Gerando as legendas"],
            progress, cancelled, self._delay,
        )
        return [BlockTiming(block_id, estimate_duration(text), text) for block_id, text in blocks]


def split_by_words(boundaries: Sequence[tuple[float, float]], texts: Sequence[str]) -> list[float]:
    """Instante em que cada bloco termina, dado o (início, fim) de cada palavra falada.

    Os blocos recebem palavras na proporção do tamanho do texto de cada um. A divisa
    fica no meio da pausa entre a última palavra de um bloco e a primeira do próximo.
    """
    counts = [max(len(text.split()), 1) for text in texts]
    total_script, total_words = sum(counts), len(boundaries)
    ends, cumulative = [], 0
    for index, count in enumerate(counts[:-1]):
        cumulative += count
        cut = min(max(round(total_words * cumulative / total_script), 1), total_words - 1)
        ends.append((boundaries[cut - 1][1] + boundaries[cut][0]) / 2)
    return ends


class LocalSpeech:
    def prepare(
        self, blocks: Sequence[tuple[int, str]], mode: str, progress: Progress,
        cancelled: IsCancelled, narration_path: str = "", work_dir: Path | None = None,
    ) -> list[BlockTiming]:
        if work_dir is None:
            raise ServiceError("Falta a pasta de trabalho da narração.")
        if mode == "sintetica":
            return self._synthesize(blocks, progress, cancelled, work_dir)
        return self._align(blocks, progress, cancelled, narration_path)

    def _synthesize(self, blocks, progress, cancelled, work_dir) -> list[BlockTiming]:  # noqa: ANN001
        timings = []
        for index, (block_id, text) in enumerate(blocks):
            if cancelled():
                raise Cancelled()
            progress(int(90 * index / len(blocks)), f"Gerando a voz do bloco {index + 1}")
            target = block_audio_path(work_dir, block_id)
            synthesize_text(text, target)
            timings.append(BlockTiming(block_id, round(probe_duration(target) + 0.25, 2), text))
        progress(100, "Concluído")
        return timings

    def _align(self, blocks, progress, cancelled, narration_path) -> list[BlockTiming]:  # noqa: ANN001
        audio = Path(narration_path)
        if not audio.is_absolute() or not audio.is_file():
            raise ServiceError("A narração importada não foi encontrada.")
        total = probe_duration(audio)
        texts = [text for _, text in blocks]
        progress(10, "Transcrevendo a narração")
        words = self._transcribe(audio, progress, cancelled)
        if len(words) >= len(blocks) + 1:
            ends = split_by_words(words, texts)
        else:  # sem Whisper ou sem fala reconhecida: divide pelo tamanho do texto
            sizes = [max(len(text), 1) for text in texts]
            ends, run = [], 0
            for size in sizes[:-1]:
                run += size
                ends.append(total * run / sum(sizes))
        ends.append(total)
        timings, start = [], 0.0
        for (block_id, text), end in zip(blocks, ends):
            timings.append(BlockTiming(block_id, round(float(max(end - start, 1.0)), 2), text))
            start = end
        progress(100, "Concluído")
        return timings

    @staticmethod
    def _transcribe(audio: Path, progress: Progress, cancelled: IsCancelled) -> list[tuple[float, float]]:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.info("faster-whisper ausente: usando a divisão por tamanho do texto")
            return []
        try:
            import numpy as np

            # O FFmpeg decodifica (16 kHz, mono): evita depender do leitor de áudio do Whisper.
            with tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp) / "audio.raw"
                run_ffmpeg(["-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", "16000",
                            str(raw)], cancelled)
                samples = np.frombuffer(raw.read_bytes(), dtype=np.int16).astype(np.float32)
            model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(
                samples / 32768.0, language="pt", word_timestamps=True, vad_filter=True
            )
            words = []
            for segment in segments:
                if cancelled():
                    raise Cancelled()
                words += [(w.start, w.end) for w in (segment.words or [])]
            return words
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - modelo não baixou, sem memória etc.
            log.warning("Whisper falhou: %s", type(exc).__name__)
            progress(60, "Whisper indisponível; dividindo pelo tamanho do texto")
            return []
