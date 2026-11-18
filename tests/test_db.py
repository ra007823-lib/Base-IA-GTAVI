from __future__ import annotations

import sqlite3
import stat

import pytest

from trinca.context import seed_demo
from trinca.db import Repository
from trinca.pipeline.contracts import BlockDraft, CuriosityDraft
from trinca.security import ValidationError


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "teste.sqlite3")
    yield repository
    repository.close()


def test_database_file_is_private(tmp_path, repo):
    mode = stat.S_IMODE((tmp_path / "teste.sqlite3").stat().st_mode)
    assert mode == 0o600


def test_updates_only_accept_known_columns(repo):
    script_id = repo.create_script("Roteiro", [BlockDraft(None, "texto", "cena")])
    with pytest.raises(ValueError):
        repo.update_script(script_id, **{"title = 'x', status": "aprovado"})
    with pytest.raises(ValueError):
        repo.update_script(script_id, created_at="ontem")
    with pytest.raises(sqlite3.IntegrityError):
        repo.update_script(script_id, status="estado-inventado")
    assert repo.get_script(script_id)["status"] == "em_roteiro"


def test_text_with_sql_is_stored_as_data(repo):
    hostile = "x'); DROP TABLE channels; --"
    repo.add_channel("UC" + "a" * 22, hostile)
    assert repo.list_channels()[0]["name"] == hostile
    with pytest.raises(ValidationError):
        repo.add_channel("UC" + "a" * 22, "repetido")


def test_script_lifecycle_and_cascade(repo):
    channel_id = repo.add_channel("UC" + "b" * 22, "Canal")
    video_id = repo.add_video(channel_id, "abcDEF12345", "Vídeo", "2026-11-16T10:00:00")
    assert repo.add_video(channel_id, "abcDEF12345", "Vídeo", "2026-11-16T10:00:00") is None
    repo.add_curiosities(video_id, [CuriosityDraft(1, 9, "Título", "Descrição", "Cena")])
    (curiosity,) = repo.list_curiosities()
    script_id = repo.create_script("Roteiro", [BlockDraft(curiosity["id"], "texto", "cena")])
    assert repo.list_curiosities()[0]["status"] == "usada"
    assert repo.script_sources(script_id)[0]["channel_name"] == "Canal"
    repo.delete_script(script_id)
    assert repo.list_curiosities()[0]["status"] == "nova"
    assert repo.list_blocks(script_id) == []
    repo.remove_channel(channel_id)
    assert repo.list_videos() == [] and repo.list_curiosities() == []


def test_demo_seed_runs_once(repo):
    seed_demo(repo)
    seed_demo(repo)
    assert len(repo.list_channels()) == 3
    assert len(repo.list_videos()) == 3
    assert repo.pipeline_counts()["publicados"] == 1
    assert repo.usage_today()["youtube"] == 3


def _video_with_curiosities(repo, youtube_id, count=3):
    channel_id = repo.ensure_channel("UC" + youtube_id[:1] * 22, f"Canal {youtube_id}")
    video_id = repo.add_video(channel_id, youtube_id, f"Vídeo {youtube_id}", "2026-11-16T10:00:00")
    repo.add_curiosities(
        video_id, [CuriosityDraft(i * 10, i * 10 + 5, f"C{i}", "Descrição", "Cena") for i in range(count)]
    )
    return [c["id"] for c in repo.list_curiosities() if c["video_id"] == video_id]


def test_each_source_video_is_used_only_once(repo):
    first = _video_with_curiosities(repo, "aaaaaaaaaaa")
    second = _video_with_curiosities(repo, "bbbbbbbbbbb")
    assert repo.pipeline_counts()["curiosidades_novas"] == 6

    # Um roteiro pode usar várias curiosidades do mesmo vídeo.
    script_id = repo.create_script(
        "Roteiro A", [BlockDraft(first[0], "t", "c"), BlockDraft(first[1], "t", "c")]
    )
    by_id = {c["id"]: c for c in repo.list_curiosities()}
    assert by_id[first[2]]["video_used"] == 1 and by_id[first[2]]["status"] == "nova"
    assert by_id[second[0]]["video_used"] == 0
    assert repo.pipeline_counts()["curiosidades_novas"] == 3
    assert {v["youtube_id"]: v["used"] for v in repo.list_videos()} == {
        "aaaaaaaaaaa": 1, "bbbbbbbbbbb": 0}

    # Outro roteiro não pode usar o que sobrou do mesmo vídeo, nem misturado com outro.
    with pytest.raises(ValidationError, match="só pode ser usado uma vez"):
        repo.create_script("Roteiro B", [BlockDraft(first[2], "t", "c")])
    with pytest.raises(ValidationError):
        repo.create_script("Roteiro B", [BlockDraft(second[0], "t", "c"), BlockDraft(first[2], "t", "c")])
    assert len(repo.list_scripts()) == 1
    assert {c["id"]: c for c in repo.list_curiosities()}[second[0]]["status"] == "nova"

    # Um rascunho excluído devolve o vídeo.
    repo.delete_script(script_id)
    assert repo.list_videos()[0]["used"] == 0
    script_id = repo.create_script("Roteiro C", [BlockDraft(first[2], "t", "c")])

    # Depois de agendado ou publicado, o vídeo fica usado em definitivo.
    repo.upsert_publication(script_id, "tiktok", "T", "D", "#h")
    (publication,) = repo.list_publications(script_id)
    repo.update_publication(publication["id"], title="Só texto")
    assert not repo.is_video_used("aaaaaaaaaaa")
    repo.update_publication(publication["id"], status="agendado")
    assert repo.is_video_used("aaaaaaaaaaa") and not repo.is_video_used("bbbbbbbbbbb")
    repo.delete_script(script_id)
    used = {v["youtube_id"]: v["used"] for v in repo.list_videos()}
    assert used == {"aaaaaaaaaaa": 1, "bbbbbbbbbbb": 0}
    with pytest.raises(ValidationError):
        repo.create_script("Roteiro D", [BlockDraft(first[0], "t", "c")])

    # Nem apagando o canal o vídeo volta: buscas e radar não o trazem de novo.
    channel = next(c for c in repo.list_channels(monitored_only=False) if c["name"].endswith("aaaaaaaaaaa"))
    repo.remove_channel(channel["id"])
    assert "aaaaaaaaaaa" in repo.all_video_ids()
    new_channel = repo.ensure_channel("UC" + "z" * 22, "Outro")
    assert repo.add_video(new_channel, "aaaaaaaaaaa", "De novo", "2026-11-17T10:00:00") is None


def test_theme_channels_are_not_monitored_until_added(repo):
    channel_id = repo.ensure_channel("UC" + "t" * 22, "Achado por tema")
    assert repo.ensure_channel("UC" + "t" * 22, "Outro nome") == channel_id
    assert repo.list_channels() == []
    assert repo.add_channel("UC" + "t" * 22, "Nome oficial", "UU" + "t" * 22) == channel_id
    (channel,) = repo.list_channels()
    assert (channel["name"], channel["uploads_playlist"]) == ("Nome oficial", "UU" + "t" * 22)
    with pytest.raises(ValidationError):
        repo.add_channel("UC" + "t" * 22, "Repetido")


def test_themes_are_saved_without_duplicates(repo):
    first = repo.save_theme("Segredos do mapa")
    assert repo.save_theme("segredos do MAPA") == first
    repo.save_theme("Outro tema")
    assert len(repo.list_themes()) == 2
    repo.remove_theme(first)
    assert [t["query"] for t in repo.list_themes()] == ["Outro tema"]
