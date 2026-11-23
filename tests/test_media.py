"""Narração, legendas e montagem (FFmpeg real, com clipes gerados na hora)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from trinca.pipeline.assembly import FfmpegAssembler
from trinca.pipeline.contracts import Cancelled, RenderBlock, RenderJob, ServiceError
from trinca.pipeline.media import (
    build_ass, ffmpeg_path, probe_duration, script_dir, split_caption,
)
from trinca.pipeline.narration import LocalSpeech, split_by_words


def quiet(percent, label):
    pass


def never():
    return False


def test_split_caption_and_ass_timing():
    assert split_caption("a b c d e f g") == ["a b c", "d e f", "g"]
    ass = build_ass("um dois três quatro", 4.0, "Clássico")
    assert "PlayResY: 1920" in ass
    assert ass.count("Dialogue:") == 2
    assert "0:00:04.00" in ass  # o último trecho termina no fim do bloco
    assert "{" not in build_ass("texto {malicioso} \\N", 2, "Neon").split("[Events]")[1].split(",,")[1]


def test_split_by_words_cuts_in_the_pause():
    words = [(0.0, 0.4), (0.5, 0.9), (1.0, 1.4), (2.4, 2.8), (2.9, 3.3), (3.4, 3.8)]
    ends = split_by_words(words, ["um dois três", "quatro cinco seis"])
    assert ends == [pytest.approx(1.9)]  # meio da pausa entre 1.4 e 2.4


def test_align_falls_back_to_text_size_without_whisper(tmp_path, monkeypatch):
    audio = tmp_path / "voz.wav"
    subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=10", str(audio)], check=True,
    )
    monkeypatch.setattr(LocalSpeech, "_transcribe", staticmethod(lambda *a: []))
    timings = LocalSpeech().prepare(
        [(1, "a" * 100), (2, "b" * 300)], "propria", quiet, never,
        narration_path=str(audio), work_dir=tmp_path,
    )
    assert [t.block_id for t in timings] == [1, 2]
    assert timings[0].duration_s == pytest.approx(2.5, abs=0.1)
    assert sum(t.duration_s for t in timings) == pytest.approx(10, abs=0.1)
    with pytest.raises(ServiceError):
        LocalSpeech().prepare([(1, "x")], "propria", quiet, never,
                              narration_path="/nao/existe.mp3", work_dir=tmp_path)


def _make(tmp_path: Path, name: str, source: str, seconds: int) -> Path:
    path = tmp_path / name
    subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"{source}=size=1280x720:rate=30:duration={seconds}", str(path)], check=True,
    )
    return path


def test_ffmpeg_render_makes_vertical_video_with_narration(tmp_path):
    clip_a = _make(tmp_path, "a.mp4", "testsrc2", 4)
    clip_b = _make(tmp_path, "b.mp4", "smptebars", 1)  # mais curto que o bloco: congela o último quadro
    voice = tmp_path / "voz.wav"
    subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=300:duration=7", str(voice)], check=True,
    )
    job = RenderJob(
        7, "Teste de montagem", (
            RenderBlock(1, str(clip_a), 0.0, 3.0, "primeira legenda do bloco", 0.0),
            RenderBlock(2, str(clip_b), 0.0, 3.0, "segunda legenda", 3.0),
        ), "propria", str(voice), "Neon", str(tmp_path / "saida"),
    )
    final = Path(FfmpegAssembler().render(job, quiet, never))
    assert final.is_file() and final.is_relative_to(tmp_path / "saida")
    assert probe_duration(final) == pytest.approx(6.0, abs=0.3)
    info = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(final)],
                          capture_output=True, text=True).stderr
    assert "1080x1920" in info and "Audio: aac" in info
    assert final.parent == (tmp_path / "saida" / "cortes").resolve()
    folder = script_dir(tmp_path / "saida", 7, "Teste de montagem")
    assert list(folder.iterdir()) == []  # temporários removidos


def test_ffmpeg_render_rejects_missing_media_and_can_be_cancelled(tmp_path):
    base = dict(narration_mode="propria", narration_path=str(tmp_path / "x.wav"),
                caption_style="Neon", output_dir=str(tmp_path / "saida"))
    missing = RenderJob(1, "T", (RenderBlock(1, "/nao/existe.mp4", 0, 2, "x", 0),), **base)
    with pytest.raises(ServiceError):
        FfmpegAssembler().render(missing, quiet, never)
    clip = _make(tmp_path, "a.mp4", "testsrc2", 2)
    voice = tmp_path / "x.wav"
    subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=300:duration=2", str(voice)], check=True,
    )
    job = RenderJob(1, "T", (RenderBlock(1, str(clip), 0, 2, "x", 0),), **base)
    with pytest.raises(Cancelled):
        FfmpegAssembler().render(job, quiet, lambda: True)


def test_cut_range_keeps_output_between_30s_and_90s():
    from trinca.pipeline.media import cut_range

    assert cut_range(100, 110, 600, 30, 90) == (100, 130)  # curto demais: estende
    assert cut_range(100, 400, 600, 30, 90) == (100, 190)  # longo demais: corta
    assert cut_range(100, 150, 600, 30, 90) == (100, 150)  # já está na faixa
    assert cut_range(590, 600, 600, 30, 90) == (570, 600)  # fim do vídeo: recua o início
    assert cut_range(-5, 40, 600, 30, 90) == (0, 40)


def test_ffmpeg_cut_keeps_original_audio_and_full_frame(tmp_path):
    source = tmp_path / "fonte.mp4"
    subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=1280x720:rate=30:duration=12", "-f", "lavfi", "-i",
         "sine=frequency=500:duration=12", "-shortest", str(source)], check=True,
    )
    job = RenderJob(
        9, "Corte real", (RenderBlock(1, str(source), 4.0, 9.0, "", 0.0),),
        "original", "", "Neon", str(tmp_path / "saida"),
    )
    final = Path(FfmpegAssembler().render(job, quiet, never))
    assert probe_duration(final) == pytest.approx(5.0, abs=0.3)
    info = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(final)],
                          capture_output=True, text=True).stderr
    assert "1080x1920" in info and "Audio: aac" in info


def test_original_audio_cut_opens_with_hook_and_saves_cover(tmp_path, monkeypatch):
    clip = _make(tmp_path, "origem.mp4", "testsrc2", 6)

    def fake_voice(text, target):  # sem rede: um tom de 2 s no lugar da voz
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=400:duration=2", str(target)], check=True,
        )

    monkeypatch.setattr("trinca.pipeline.assembly.synthesize_text", fake_voice)
    job = RenderJob(
        9, "Gancho", (RenderBlock(1, str(clip), 1.0, 5.0, "", 0.0, "Olha só o que acontece", 3.0),),
        "original", "", "Neon", str(tmp_path / "saida"),
    )
    final = Path(FfmpegAssembler().render(job, quiet, never))
    # gancho (2 s de voz + folga, no mínimo 3 s) + corte de 4 s
    assert probe_duration(final) == pytest.approx(3.0 + 4.0, abs=0.4)
    assert final.with_suffix(".jpg").is_file()  # capa ao lado do corte
    assert list(script_dir(tmp_path / "saida", 9, "Gancho").iterdir()) == []


def test_hook_intro_uses_fallback_spot_and_default_text(tmp_path, monkeypatch):
    from trinca.pipeline.contracts import default_hook

    assert default_hook("", "Um fato. " + "palavra " * 30).startswith("Um fato.")
    assert default_hook("", "") == ""
    clip = _make(tmp_path, "origem.mp4", "testsrc2", 6)

    def fake_voice(text, target):
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=400:duration=2", str(target)], check=True,
        )

    monkeypatch.setattr("trinca.pipeline.assembly.synthesize_text", fake_voice)
    job = RenderJob(
        10, "Sem ponto alto", (RenderBlock(1, str(clip), 1.0, 5.0, "", 0.0, "Introdução simples", -1.0),),
        "original", "", "Neon", str(tmp_path / "saida"),
    )
    final = Path(FfmpegAssembler().render(job, quiet, never))
    assert probe_duration(final) == pytest.approx(3.0 + 4.0, abs=0.4)
