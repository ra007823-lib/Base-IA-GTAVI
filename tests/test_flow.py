"""Percorre o caminho completo do modo de demonstração pela interface."""

from __future__ import annotations

from pathlib import Path

from trinca.security import video_url
from trinca.ui.main_window import PAGES, MainWindow

from conftest import wait_task


def _select_row(table, text: str) -> None:
    for line in range(table.rowCount()):
        if text in table.item(line, 0).text():
            table.selectRow(line)
            return
    raise AssertionError(f"Linha não encontrada: {text}")


def test_every_page_opens(qapp, ctx):
    window = MainWindow(ctx)
    for key, _, _ in PAGES:
        window.show_page(key)
        assert window.stack.currentWidget() is window.pages[key]
    window.close()


def test_full_demo_flow(qapp, ctx, dialogs, tmp_path):
    repo = ctx.repo
    window = MainWindow(ctx)
    pages = window.pages

    # 1. Radar: detecta um vídeo novo e analisa um vídeo de exemplo.
    window.show_page("radar")
    before = len(repo.list_videos())
    pages["radar"].check_now()
    wait_task(qapp, ctx)
    assert len(repo.list_videos()) == before + 2  # um vídeo novo por canal com fila
    _select_row(pages["radar"].videos, "Testei a polícia")
    pages["radar"].analyze_selected()
    wait_task(qapp, ctx)
    police = [c for c in repo.list_curiosities() if "polícia" in c["video_title"]]
    assert len(police) == 3

    # 2. Curiosidades: seleciona duas e gera o roteiro.
    window.show_page("curiosidades")
    repo.set_curiosity_status([police[0]["id"], police[1]["id"]], "selecionada")
    pages["curiosidades"].refresh()
    pages["curiosidades"].generate()
    wait_task(qapp, ctx)
    script = repo.list_scripts(("em_roteiro",))[0]
    assert window.stack.currentWidget() is pages["roteiros"]
    assert len(repo.list_blocks(script["id"])) == 2

    # 3. Roteiros: envia para gravação.
    pages["roteiros"].send_to_recording()
    assert repo.get_script(script["id"])["status"] == "aguardando_gravacao"

    # 4. Importação: sem material não avança; com material, gera legendas.
    window.show_page("importacao")
    pages["importacao"].prepare()
    assert "Importe o vídeo de todos os blocos" in dialogs[-1]
    pages["importacao"].fill_demo()
    assert repo.get_script(script["id"])["status"] == "gravado"
    pages["importacao"].prepare()
    wait_task(qapp, ctx)
    assert repo.get_script(script["id"])["status"] == "aguardando_revisao"
    assert window.stack.currentWidget() is pages["revisao"]

    # 5. Revisão: não aprova sem renderizar; um ajuste invalida a renderização.
    review = pages["revisao"]
    review.approve()
    assert repo.get_script(script["id"])["status"] == "aguardando_revisao"
    review.render()
    wait_task(qapp, ctx)
    assert repo.get_script(script["id"])["render_path"]
    review.end.setValue(review.end.value() - 1)
    review.apply_adjust()
    assert repo.get_script(script["id"])["render_path"] == ""
    review.render()
    wait_task(qapp, ctx)
    review.approve()
    assert repo.get_script(script["id"])["status"] == "aprovado"
    assert window.stack.currentWidget() is pages["publicacao"]

    # 6. Publicação: textos, crédito obrigatório, pacote e agendamento.
    publishing = pages["publicacao"]
    publishing.scripts.setCurrentIndex(publishing.scripts.findData(script["id"]))
    publishing.generate_copy()
    wait_task(qapp, ctx)
    source_url = video_url(police[0]["video_youtube_id"])
    instagram = publishing.platform_tabs["instagram"]
    assert source_url in instagram.description.toPlainText()

    credited = instagram.description.toPlainText()
    instagram.description.setPlainText("Descrição sem o crédito.")
    publishing.make_package(instagram)
    assert "crédito" in dialogs[-1]
    assert not repo.list_publications(script["id"])[0]["package_path"]
    instagram.description.setPlainText(credited)
    publishing.make_package(instagram)
    publication = next(
        p for p in repo.list_publications(script["id"]) if p["platform"] == "instagram"
    )
    package = Path(publication["package_path"])
    assert package.is_relative_to(tmp_path / "dados" / "saida")
    assert source_url in (package / "legenda.txt").read_text(encoding="utf-8")

    publishing.schedule_youtube(publishing.platform_tabs["youtube"])
    wait_task(qapp, ctx)
    youtube = next(p for p in repo.list_publications(script["id"]) if p["platform"] == "youtube")
    assert youtube["status"] == "agendado"

    # 7. Histórico e painel refletem o resultado.
    window.show_page("historico")
    assert pages["historico"].table.rowCount() == 6
    window.show_page("painel")
    assert pages["painel"].values["publicados"].text() == "1"
    window.close()


def test_failed_task_can_be_retried(qapp, ctx):
    window = MainWindow(ctx)
    attempts = []

    def work(progress, cancelled):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("falha de rede com key=AIza" + "Z" * 35)
        return "ok"

    ctx.run_task("Tarefa de teste", work, lambda result: f"Resultado: {result}")
    wait_task(qapp, ctx)
    assert "AIza" not in window.task_label.text()
    assert window.retry_button.isVisibleTo(window)
    ctx.retry()
    wait_task(qapp, ctx)
    assert window.task_label.text() == "Resultado: ok"
    assert not window.retry_button.isVisibleTo(window)
    window.close()


def test_task_can_be_cancelled(qapp, ctx):
    from trinca.pipeline.contracts import simulate

    window = MainWindow(ctx)
    ctx.run_task(
        "Tarefa longa",
        lambda progress, cancelled: simulate(["a", "b"], progress, cancelled, 5),
        lambda result: "terminou",
    )
    ctx.cancel_task()
    wait_task(qapp, ctx)
    assert "cancelado" in window.task_label.text()
    assert not ctx.can_retry
    window.close()


def test_theme_search_in_demo_mode(qapp, ctx, dialogs):
    repo = ctx.repo
    window = MainWindow(ctx)
    radar = window.pages["radar"]
    window.show_page("radar")
    before = len(repo.list_videos())

    radar.theme_input.setText("x")
    radar.search_theme()
    assert "pelo menos 2 caracteres" in dialogs[-1] and not ctx.busy

    radar.theme_input.setText("segredos do mapa")
    radar.search_theme()
    wait_task(qapp, ctx)
    videos = repo.list_videos()
    assert len(videos) == before + 2
    assert sum(v["theme"] == "segredos do mapa" for v in videos) == 2
    assert [t["query"] for t in repo.list_themes()] == ["segredos do mapa"]
    assert radar.themes.rowCount() == 1

    # Escolher um tema salvo preenche o campo de busca.
    radar.theme_input.clear()
    radar.themes.selectRow(0)
    assert radar.theme_input.text() == "segredos do mapa"
    window.close()


def test_curiosities_of_a_used_video_are_blocked(qapp, ctx, dialogs):
    repo = ctx.repo
    window = MainWindow(ctx)
    page = window.pages["curiosidades"]
    window.show_page("curiosidades")

    # O vídeo de exemplo já publicado bloqueia as duas curiosidades que sobraram dele.
    leftover = [c for c in repo.list_curiosities() if c["video_used"] and c["status"] != "usada"]
    assert len(leftover) == 2
    group = page.tree.topLevelItem(0)
    states = [group.child(i).text(2) for i in range(group.childCount())]
    assert sum("Vídeo já usado" in state for state in states) == 2

    # Selecionar pela tela é recusado.
    for i in range(group.childCount()):
        group.child(i).setSelected(True)
    page.set_status("selecionada")
    assert "bloqueadas" in dialogs[-1]
    assert repo.list_curiosities("selecionada") == []

    # Mesmo forçando o estado no banco, o roteiro não pode ser gerado.
    repo.set_curiosity_status([c["id"] for c in leftover], "selecionada")
    page.refresh()
    assert not page.generate_button.isEnabled()
    assert "(0)" in page.generate_button.text()
    window.show_page("painel")
    assert window.pages["painel"].values["curiosidades_novas"].text() == "0"
    window.close()


def test_source_download_without_authorization_prompt(qapp, ctx, dialogs, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    repo = ctx.repo
    window = MainWindow(ctx)
    pages = window.pages
    window.show_page("radar")
    pages["radar"].check_now()
    wait_task(qapp, ctx)
    _select_row(pages["radar"].videos, "Testei a polícia")
    pages["radar"].analyze_selected()
    wait_task(qapp, ctx)
    police = [c for c in repo.list_curiosities() if "polícia" in c["video_title"]]
    repo.set_curiosity_status([police[0]["id"]], "selecionada")
    pages["curiosidades"].refresh()
    pages["curiosidades"].generate()
    wait_task(qapp, ctx)
    script = repo.list_scripts(("em_roteiro",))[0]
    pages["roteiros"].send_to_recording()
    imports = pages["importacao"]
    imports.refresh()
    block = repo.list_blocks(script["id"])[0]
    assert block["channel_permission"] == "sem_autorizacao"

    # O download não pede mais autorização: baixa direto e liga o trecho ao bloco.
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    imports.download_source(block["id"])
    wait_task(qapp, ctx)
    assert repo.list_blocks(script["id"])[0]["media_path"]
    window.close()


def test_ytdlp_downloader_rejects_bad_video_id(tmp_path):
    import pytest as _pytest
    from trinca.pipeline.download import YtDlpDownloader
    from trinca.security import ValidationError

    with _pytest.raises(ValidationError):
        YtDlpDownloader().fetch("../x", tmp_path / "a.mp4", lambda *_: None, lambda: False)


def test_original_audio_mode_skips_narration_and_goes_to_review(qapp, ctx, dialogs, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    repo = ctx.repo
    window = MainWindow(ctx)
    pages = window.pages
    window.show_page("radar")
    pages["radar"].check_now()
    wait_task(qapp, ctx)
    _select_row(pages["radar"].videos, "Testei a polícia")
    pages["radar"].analyze_selected()
    wait_task(qapp, ctx)
    police = [c for c in repo.list_curiosities() if "polícia" in c["video_title"]]
    repo.set_curiosity_status([police[0]["id"]], "selecionada")
    pages["curiosidades"].refresh()
    pages["curiosidades"].generate()
    wait_task(qapp, ctx)
    script = repo.list_scripts(("em_roteiro",))[0]
    pages["roteiros"].send_to_recording()
    imports = pages["importacao"]
    imports.refresh()
    imports.original.setChecked(True)
    assert repo.get_script(script["id"])["original_audio"] == 1
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("contrato assinado em 2026", True))
    imports.download_source(repo.list_blocks(script["id"])[0]["id"])
    wait_task(qapp, ctx)
    imports.prepare()  # sem narração própria importada e mesmo assim avança
    assert repo.get_script(script["id"])["status"] == "aguardando_revisao"
    assert window.stack.currentWidget() is pages["revisao"]
    window.close()


def test_library_lists_deletes_cut_and_raw_files(qapp, ctx, dialogs, monkeypatch):
    from trinca.pipeline.media import cuts_dir, raw_dir
    from trinca.ui.main_window import MainWindow

    monkeypatch.setattr("trinca.ui.pages.library.confirm", lambda *a, **k: True)
    window = MainWindow(ctx)
    page = window.pages["biblioteca"]
    repo = ctx.repo
    script_id = repo.list_scripts()[0]["id"]
    cut = cuts_dir(ctx.output_dir()) / "0001-teste.mp4"
    cut.write_bytes(b"x")
    cut.with_suffix(".jpg").write_bytes(b"x")
    raw = raw_dir(ctx.output_dir()) / "abc.mp4"
    raw.write_bytes(b"x")
    repo.update_script(script_id, render_path=str(cut), status="aprovado")
    block = repo.list_blocks(script_id)[0]
    repo.update_block(block["id"], media_path=str(raw))

    page.refresh()
    assert page.cut_table.rowCount() == 1 and page.raw_table.rowCount() == 1
    page.cut_table.selectRow(0)
    page.delete_cut()
    assert not cut.exists() and not cut.with_suffix(".jpg").exists()
    saved = repo.get_script(script_id)
    assert saved["render_path"] == "" and saved["status"] == "aguardando_revisao"

    page.raw_table.selectRow(0)
    page.delete_raw()
    assert not raw.exists()
    assert repo.list_blocks(script_id)[0]["media_path"] == ""
