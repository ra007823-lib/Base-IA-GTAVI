"""Modo real pela interface, com as APIs substituídas por respostas simuladas."""

from __future__ import annotations

import pytest

from trinca.__main__ import Launcher
from trinca.config import YOUTUBE_DAILY_QUOTA, load_demo_mode
from trinca.context import build_context
from trinca.credentials import CredentialStore
from trinca.pipeline.analysis import GeminiAnalyst
from trinca.pipeline.radar import YouTubeRadar
from trinca.pipeline.script import ClaudeWriter
from trinca.pipeline.youtube_api import YouTubeApi
from trinca.ui.main_window import MainWindow

from conftest import MemoryKeyring, wait_task
from test_integrations import (
    CHANNEL, KEY, FakeClaude, FakeFetch, FakeGemini, _channel_payload, _moment, _video_item,
)


@pytest.fixture
def real_ctx(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TRINCA_DATA_DIR", str(tmp_path / "dados"))
    context = build_context(demo=False, delay=0, credentials=CredentialStore(MemoryKeyring()))
    yield context
    context.repo.close()


def test_real_mode_starts_empty_and_asks_for_keys(qapp, real_ctx, dialogs, tmp_path):
    assert not real_ctx.demo
    assert real_ctx.repo.list_channels() == []
    assert (tmp_path / "dados" / "trinca.sqlite3").exists()
    assert not (tmp_path / "dados" / "demo.sqlite3").exists()
    window = MainWindow(real_ctx)
    window.show_page("radar")
    window.show_page("configuracoes")
    assert "Faltam as chaves de" in window.pages["configuracoes"].mode_label.text()
    window.close()


def test_real_mode_flow_from_channel_to_script(qapp, real_ctx, dialogs):
    repo = real_ctx.repo
    listing = {"items": [{"contentDetails": {"videoId": "novoVideo01"}}]}
    details = {"items": [_video_item("novoVideo01", "Gameplay nova", "PT50M")]}
    fetch = FakeFetch((200, _channel_payload()), (200, listing), (200, details))
    gemini = FakeGemini(
        {"curiosities": [_moment("03:00", "03:20", "Chuva na praia")]},
        {"curiosities": [_moment("22:00", "22:30", "Rádio do bairro")]},
        {"curiosities": []},
    )
    services = real_ctx.services
    services.radar = YouTubeRadar(YouTubeApi(lambda: KEY, fetch))
    services.analyst = GeminiAnalyst(lambda: KEY, lambda: real_ctx.models["gemini"], lambda k: gemini)

    window = MainWindow(real_ctx)
    radar = window.pages["radar"]
    window.show_page("radar")
    radar.resolve_channel("@CanalTeste")
    wait_task(qapp, real_ctx)
    (channel,) = repo.list_channels()
    assert (channel["youtube_id"], channel["name"]) == (CHANNEL, "Canal de Teste")

    radar.check_now()
    wait_task(qapp, real_ctx)
    (video,) = repo.list_videos()
    assert (video["youtube_id"], video["duration_s"]) == ("novoVideo01", 3000)
    assert repo.usage_today()["youtube"] == 3  # 1 da busca do canal + 2 da verificação

    radar.videos.selectRow(0)
    radar.analyze_selected()
    wait_task(qapp, real_ctx)
    curiosities = repo.list_curiosities()
    assert [c["title"] for c in curiosities] == ["Chuva na praia", "Rádio do bairro"]
    usage = repo.usage_today()
    assert (usage["gemini"], usage["gemini_video_s"]) == (3, 3000)
    assert gemini.calls[0]["model"] == "gemini-4-hydrogen"

    ids = [c["id"] for c in curiosities]
    claude = FakeClaude({"title": "2 detalhes de GTA VI", "blocks": [
        {"curiosity_id": ids[0], "text": "Repara na chuva."},
        {"curiosity_id": ids[1], "text": "O rádio acompanha o bairro."},
    ]})
    services.writer = ClaudeWriter(lambda: "sk-ant-teste", lambda: real_ctx.models["claude"],
                                   lambda k: claude)
    repo.set_curiosity_status(ids, "selecionada")
    window.show_page("curiosidades")
    window.pages["curiosidades"].generate()
    wait_task(qapp, real_ctx)
    (script,) = repo.list_scripts()
    assert script["title"] == "2 detalhes de GTA VI"
    assert claude.calls[0][1]["model"] == "claude-opus-5-5"
    assert window.stack.currentWidget() is window.pages["roteiros"]
    window.close()


def test_radar_pauses_when_daily_quota_is_spent(qapp, real_ctx, dialogs):
    repo = real_ctx.repo
    repo.add_channel(CHANNEL, "Canal", "UU" + "c" * 22)
    repo.add_usage("youtube", YOUTUBE_DAILY_QUOTA - 2)
    window = MainWindow(real_ctx)
    window.pages["radar"].check_now()
    assert not real_ctx.busy
    assert "Radar pausado" in window.task_label.text()
    window.close()


def test_model_setting_is_validated_and_used(qapp, real_ctx, dialogs):
    window = MainWindow(real_ctx)
    window.show_page("configuracoes")
    settings = window.pages["configuracoes"]
    settings.model_inputs["gemini"].setCurrentText("gemini-4-argon")
    settings.save_model("gemini")
    assert real_ctx.models["gemini"] == "gemini-4-argon"
    assert real_ctx.repo.get_setting("gemini_model") == "gemini-4-argon"
    settings.model_inputs["claude"].setCurrentText("modelo inválido!")
    settings.save_model("claude")
    assert real_ctx.models["claude"] == "claude-opus-5-5"
    assert "Nome de modelo inválido" in dialogs[-1]
    window.close()


def test_switching_between_demo_and_real(qapp, tmp_path, monkeypatch, dialogs):
    monkeypatch.setenv("TRINCA_DATA_DIR", str(tmp_path / "dados"))
    store = CredentialStore(MemoryKeyring())
    launcher = Launcher(lambda demo: build_context(demo=demo, delay=0, credentials=store))
    assert load_demo_mode() is True
    launcher.start(load_demo_mode())
    first = launcher.window
    assert first.ctx.demo and len(first.ctx.repo.list_channels()) == 3

    first.show_page("configuracoes")
    first.pages["configuracoes"].toggle_mode()
    qapp.processEvents()
    qapp.processEvents()
    second = launcher.window
    assert second is not first and not second.ctx.demo
    assert second.ctx.repo.list_channels() == []  # dados fictícios não vão para o modo real
    assert load_demo_mode() is False

    second.show_page("configuracoes")
    second.pages["configuracoes"].toggle_mode()
    qapp.processEvents()
    qapp.processEvents()
    assert launcher.window.ctx.demo and load_demo_mode() is True
    launcher.window.close()
    launcher.window.ctx.repo.close()


def test_theme_search_in_real_mode_credits_the_video_channel(qapp, real_ctx, dialogs):
    repo = real_ctx.repo
    other = "UC" + "d" * 22
    found = {"items": [{"id": {"videoId": "temaVideo01"}}]}
    details = {"items": [_video_item("temaVideo01", "Achado pela busca", "PT12M", channel=other,
                                     channel_name="Outro Canal")]}
    fetch = FakeFetch((200, found), (200, details))
    real_ctx.services.radar = YouTubeRadar(YouTubeApi(lambda: KEY, fetch))
    window = MainWindow(real_ctx)
    radar = window.pages["radar"]
    window.show_page("radar")

    radar.theme_input.setText("  curiosidades do espaço ")
    radar.search_theme()
    wait_task(qapp, real_ctx)
    (video,) = repo.list_videos()
    assert (video["theme"], video["channel_name"]) == ("curiosidades do espaço", "Outro Canal")
    assert repo.usage_today()["youtube"] == 101
    assert [t["query"] for t in repo.list_themes()] == ["curiosidades do espaço"]
    # O canal do vídeo serve para o crédito, mas não entra na lista de monitorados.
    assert repo.list_channels() == []
    assert len(repo.list_channels(monitored_only=False)) == 1
    assert radar.videos.item(0, 2).text() == "curiosidades do espaço"

    repo.add_usage("youtube", YOUTUBE_DAILY_QUOTA)
    radar.search_theme()
    assert not real_ctx.busy and "cota diária" in dialogs[-1]
    window.close()
