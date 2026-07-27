from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manual_stress_editor_replaces_read_only_preview() -> None:
    html = (ROOT / "metrotrance/static/index.html").read_text(encoding="utf-8")
    assert 'id="stressPreviewEditor"' in html
    assert 'id="insertStressMark"' in html
    assert 'id="removeWordStress"' in html
    assert 'id="applyStressEdits"' in html
    assert 'id="saveStressCorrections"' in html
    assert '<pre class="stress-preview" id="stressPreview"></pre>' not in html


def test_manual_stress_editor_preserves_and_applies_edits() -> None:
    js = (ROOT / "metrotrance/static/app.js").read_text(encoding="utf-8")
    assert "function editCurrentWordStress" in js
    assert "function collectDictionaryCorrections" in js
    assert "function applyEditedStressText" in js
    assert "Ручные исправления автоматически применены перед созданием" in js
    assert "entries={...(current.dictionary||{}),...corrections}" in js


def test_manual_stress_editor_has_readable_styles() -> None:
    css = (ROOT / "metrotrance/static/styles.css").read_text(encoding="utf-8")
    assert ".stress-preview-editor{" in css
    assert "font-size:17px" in css
    assert ".stress-editor-toolbar" in css
