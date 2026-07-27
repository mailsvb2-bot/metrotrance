from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ui_labels_procedural_audio_as_technical_draft() -> None:
    html = (ROOT / "metrotrance" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Черновая техническая подложка" in html
    assert "Из моей библиотеки с правами" in html
    assert "Паспорт звука и прав" in html


def test_ui_has_rights_confirmation_and_separate_layer_levels() -> None:
    html = (ROOT / "metrotrance" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="assetRightsConfirmed"' in html
    assert 'id="musicLevel"' in html
    assert 'id="atmosphereLevel"' in html
    assert 'id="audioMixProfile"' in html
