"""Roteirista pelo Gemini e fluxo manual com o chat do Claude."""

from __future__ import annotations

import json

import pytest

from trinca.credentials import CredentialError
from trinca.pipeline.contracts import Source
from trinca.pipeline.script import (
    GeminiWriter, RoutedWriter, extract_json, manual_script_prompt, parse_pasted_copy,
    parse_pasted_script,
)
from trinca.security import ValidationError
from trinca.ui.paste_dialog import PasteDialog

from test_integrations import ITEMS, SCRIPT, FakeGemini, never, quiet

COPY = {p: {"title": "T", "description": "D", "hashtags": ["a", "b", "c"]}
        for p in ("youtube", "instagram", "tiktok")}


def test_gemini_writer_returns_script_and_asks_for_json_schema():
    client = FakeGemini(SCRIPT)
    writer = GeminiWriter(lambda: "k" * 30, lambda: "gemini-4-hydrogen", lambda key: client)
    draft = writer.write(ITEMS, 60, quiet, never)
    assert [b.curiosity_id for b in draft.blocks] == [7, 9]
    call = client.calls[0]
    assert call["store"] is False
    assert call["response_format"]["mime_type"] == "application/json"


def test_gemini_writer_copy_gets_credit_and_needs_key():
    sources = [Source("Canal A", "abcDEF12345", "Vídeo")]
    writer = GeminiWriter(lambda: "k" * 30, lambda: "gemini-4-hydrogen", lambda key: FakeGemini(COPY))
    copies = writer.platform_copy("Título", "Roteiro", sources, quiet, never)
    assert all("abcDEF12345" in c.description for c in copies)
    with pytest.raises(CredentialError):
        GeminiWriter(lambda: None, lambda: "gemini-4-hydrogen").write(ITEMS, 60, quiet, never)


def test_routed_writer_follows_the_setting():
    chosen = {"value": "claude"}
    calls = []

    class Stub:
        def __init__(self, name):
            self.name = name

        def write(self, *args):
            calls.append(self.name)

    router = RoutedWriter(lambda: chosen["value"], Stub("gemini"), Stub("claude"))
    router.write(ITEMS, 60, quiet, never)
    chosen["value"] = "gemini"
    router.write(ITEMS, 60, quiet, never)
    assert calls == ["claude", "gemini"]


@pytest.mark.parametrize("wrap", ["{}", "```json\n{}\n```", "Claro! Aqui está:\n```\n{}\n```\nFeito."])
def test_extract_json_accepts_chat_formats(wrap):
    assert extract_json(wrap.format(json.dumps(SCRIPT))) == SCRIPT


@pytest.mark.parametrize("bad", ["", "sem json", '{"title": ', "x" * 200_000])
def test_extract_json_rejects_garbage(bad):
    with pytest.raises(ValidationError):
        extract_json(bad)


def test_pasted_script_is_validated_like_any_ai_answer():
    draft = parse_pasted_script("```json\n" + json.dumps(SCRIPT) + "\n```", ITEMS)
    assert draft.title == SCRIPT["title"]
    invented = {"title": "x", "blocks": [{"curiosity_id": 999, "text": "inventado"}]}
    with pytest.raises(ValidationError):
        parse_pasted_script(json.dumps(invented), ITEMS)
    copies = parse_pasted_copy(json.dumps(COPY), [Source("Canal A", "abcDEF12345", "V")])
    assert {c.platform for c in copies} == {"youtube", "instagram", "tiktok"}


def test_paste_dialog_keeps_open_on_bad_answer_and_returns_draft(qapp):
    prompt = manual_script_prompt(ITEMS, 60)
    assert "JSON" in prompt and '"curiosity_id": 7' in prompt
    dialog = PasteDialog(None, "t", prompt, lambda text: parse_pasted_script(text, ITEMS))
    dialog.answer.setPlainText("não é json")
    assert dialog.submit() is False and dialog.result_value is None and dialog.error.text()
    dialog.answer.setPlainText(json.dumps(SCRIPT))
    assert dialog.submit() is True
    assert dialog.result_value.title == SCRIPT["title"]
