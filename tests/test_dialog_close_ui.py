from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dialog_close_buttons_never_submit_forms() -> None:
    html = (ROOT / "metrotrance/static/index.html").read_text(encoding="utf-8")
    assert html.count('type="button" class="close" data-dialog-close') == 2
    assert '<button class="primary" type="submit" id="saveSoundAsset"' in html
    assert '<button class="primary" type="submit" id="saveVoice"' in html


def test_dialogs_close_by_cross_and_backdrop() -> None:
    js = (ROOT / "metrotrance/static/app.js").read_text(encoding="utf-8")
    assert "function bindDialogControls(dialog)" in js
    assert "event.target===dialog" in js
    assert "closeDialog(dialog)" in js
    assert "event.submitter?.classList.contains('close')" in js


def test_close_button_has_large_accessible_target() -> None:
    css = (ROOT / "metrotrance/static/styles.css").read_text(encoding="utf-8")
    assert "min-width:44px" in css
    assert "min-height:44px" in css
    assert "position:sticky" in css
