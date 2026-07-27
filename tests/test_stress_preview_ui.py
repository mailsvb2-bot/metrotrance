from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stress_preview_uses_dark_readable_panel():
    css = (ROOT / "metrotrance/static/styles.css").read_text(encoding="utf-8")
    assert ".stress-preview{" in css
    assert "background:#07110f" in css
    assert "color:#f2faf7" in css
    assert ".stress-vowel{" in css


def test_stress_preview_has_persistent_status_and_engine_diagnostics():
    html = (ROOT / "metrotrance/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "metrotrance/static/app.js").read_text(encoding="utf-8")
    assert 'id="stressPreviewStatus"' in html
    assert 'id="stressPreviewWrap"' in html
    assert "result.engine==='silero_stress'" in js
    assert "Добавлено ударений" in js
    assert "Проверка не выполнена" in js
