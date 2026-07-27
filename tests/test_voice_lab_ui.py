from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ui_has_human_voice_lab_and_no_false_automatic_naturalness_claim() -> None:
    html = (ROOT / "metrotrance" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "metrotrance" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="voiceTestButton"' in html
    assert 'id="voiceLabResults"' in html
    assert "Слепой тест голоса — 30–45 секунд" in html
    assert "/api/voice/quality/approve" in js
    assert "/api/voice/quality/reject" in js
    assert "/api/voice/reference" in js
    assert "Живость и сходство автоматически не объявляются" in js
    assert "Слепой вариант" in js
    assert "data-rating" in js
    assert "collectPayload('voice_test')" in js


def test_studio_masters_are_not_described_as_chatterbox_audio_prompts() -> None:
    html = (ROOT / "metrotrance" / "static" / "index.html").read_text(encoding="utf-8")
    provider = (ROOT / "metrotrance" / "providers" / "chatterbox_tts.py").read_text(encoding="utf-8")

    assert "Они больше не передаются TTS как аудиореференсы с музыкой" in html
    assert "prompt_values" not in provider
    assert "prompt = reference_audio" in provider
