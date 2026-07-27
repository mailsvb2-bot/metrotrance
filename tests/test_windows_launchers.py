import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BAT_FILES = [
    "INSTALL_WINDOWS.bat",
    "REPAIR_QWEN_TTS.bat",
    "START_METROTRANCE.bat",
    "START_WITH_CONSOLE.bat",
    "CHECK_METROTRANCE.bat",
    "CHECK_PACKAGE_FILES.bat",
    "INSTALL_CHATTERBOX_OPTIONAL.bat",
    "INSTALL_LOCAL_AI.bat",
    "RESTART_METROTRANCE.bat",
    "INSTALL_RUSSIAN_STRESS.bat",
    "REPAIR_RUSSIAN_STRESS_MODEL.bat",
    "FIX_RUNTIME_AND_STRESS.bat",
    "UPDATE_TO_0_3_1.bat",
]


def test_old_windows_batch_files_are_ascii_crlf() -> None:
    for name in BAT_FILES:
        payload = (ROOT / name).read_bytes()
        assert not payload.startswith(b"\xef\xbb\xbf"), name
        assert all(byte < 128 for byte in payload), name
        assert not any(byte < 32 and byte not in {9, 10, 13} for byte in payload), name
        assert b"\r\n" in payload, name
        assert payload.replace(b"\r\n", b"").find(b"\n") == -1, name


def test_windows_installer_uses_short_runtime_paths() -> None:
    source = (ROOT / "windows_installer.py").read_text(encoding="utf-8")
    assert 'RUNTIME_ROOT = Path(os.environ.get("LOCALAPPDATA"' in source
    assert 'TEMP_DIR = RUNTIME_ROOT / "tmp"' in source
    assert 'PIP_CACHE_DIR = RUNTIME_ROOT / "pip-cache"' in source
    assert 'VENV_DIR = RUNTIME_ROOT / "venv"' in source
    assert 'RUNTIME_APP = RUNTIME_ROOT / "app"' in source


def test_windows_installer_does_not_require_requirements_text_files() -> None:
    source = (ROOT / "windows_installer.py").read_text(encoding="utf-8")
    assert '"requirements-core.txt"' not in source
    assert '"requirements-qwen.txt"' not in source
    assert "CORE_PACKAGES" in source
    assert "QWEN_PACKAGES" in source


def test_windows_installer_has_source_bundle_preflight() -> None:
    source = (ROOT / "windows_installer.py").read_text(encoding="utf-8")
    assert "def validate_source_bundle()" in source
    assert "validate_source_bundle()" in source
    assert "REQUIRED_SOURCE_PATHS" in source


def test_bundle_manifest_points_to_existing_files() -> None:
    manifest = json.loads((ROOT / "bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.3.1"
    assert manifest["package_kind"] == "complete"
    missing = [name for name in manifest["required_files"] if not (ROOT / name).is_file()]
    assert missing == []


def test_validate_source_bundle_passes_for_complete_tree() -> None:
    spec = importlib.util.spec_from_file_location("windows_installer", ROOT / "windows_installer.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_source_bundle()


def test_launcher_uses_fast_readiness_endpoint_and_disables_proxy() -> None:
    source = (ROOT / "metrotrance_launcher.py").read_text(encoding="utf-8")
    assert '"/api/ready"' in source
    assert 'ProxyHandler({})' in source
    assert '"/api/health"' not in source
    assert '"/"' in source


def test_api_exposes_instant_readiness_endpoint() -> None:
    source = (ROOT / "metrotrance" / "api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/ready"' in source
    assert '"product": "MetroTrance"' in source


def test_ui_and_api_expose_opus_download() -> None:
    api_source = (ROOT / "metrotrance" / "api.py").read_text(encoding="utf-8")
    html = (ROOT / "metrotrance" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "metrotrance" / "static" / "app.js").read_text(encoding="utf-8")
    assert '"opus": record.opus_path' in api_source
    assert 'id="downloadOpus"' in html
    assert "${base}/opus" in js


def test_stress_repair_uses_diagnostic_script_not_blind_assert() -> None:
    batch = (ROOT / "REPAIR_RUSSIAN_STRESS_MODEL.bat").read_text(encoding="ascii")
    script = (ROOT / "repair_russian_stress.py").read_text(encoding="utf-8")
    assert "repair_russian_stress.py" in batch
    assert "PYTHONPATH=%PROJECT_ROOT%" in batch
    assert "PYTHONUTF8=1" in batch
    assert "assert r.engine" not in batch
    assert "Raw Silero output" in script
    assert "health.json" in script
    assert "Loaded a different MetroTrance package" in script


def test_start_prepares_ascii_safe_stress_model() -> None:
    batch = (ROOT / "START_METROTRANCE.bat").read_text(encoding="ascii")
    assert "%PUBLIC%\\MetroTrance\\models\\silero_stress\\accentor.pt" in batch
    assert "REPAIR_RUSSIAN_STRESS_MODEL.bat" in batch


def test_runtime_paths_are_literal_backslash_paths_without_escape_corruption() -> None:
    for name in ["START_METROTRANCE.bat", "REPAIR_RUSSIAN_STRESS_MODEL.bat"]:
        payload = (ROOT / name).read_bytes()
        assert b"\\MetroTrance\\venv\\Scripts\\python.exe" in payload, name
        assert b"\x0b" not in payload, name
        assert b"\x07" not in payload, name
    start = (ROOT / "START_METROTRANCE.bat").read_bytes()
    repair = (ROOT / "REPAIR_RUSSIAN_STRESS_MODEL.bat").read_bytes()
    assert b"%PUBLIC%\\MetroTrance\\models\\silero_stress\\accentor.pt" in start
    assert b"%PUBLIC%\\MetroTrance\\models\\silero_stress\\accentor.pt" in repair
    assert b"metrotrance\\resources\\silero_stress\\accentor.pt" in repair


def test_stress_repair_never_passes_dp0_with_trailing_backslash_as_quoted_argument() -> None:
    batch = (ROOT / "REPAIR_RUSSIAN_STRESS_MODEL.bat").read_text(encoding="ascii")
    assert 'set "PROJECT_ROOT=%%~fI"' in batch
    assert '--project-root "%PROJECT_ROOT%"' in batch
    assert '--project-root "%~dp0"' not in batch


def test_repair_script_strips_unmatched_trailing_quote_from_project_root() -> None:
    spec = importlib.util.spec_from_file_location("repair_russian_stress", ROOT / "repair_russian_stress.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = ROOT.resolve()
    assert module._project_root(str(expected) + '"') == expected
    assert module._project_root('"' + str(expected) + '"') == expected


def test_start_uses_ascii_safe_runtime_model() -> None:
    batch = (ROOT / "START_METROTRANCE.bat").read_text(encoding="ascii")
    assert "ASCII_MODEL" in batch
    assert "%PUBLIC%\\MetroTrance" in batch


def test_repair_copies_then_loads_ascii_model() -> None:
    script = (ROOT / "repair_russian_stress.py").read_text(encoding="utf-8")
    assert "_atomic_copy(bundled, ascii_model)" in script
    assert "service._load_accentor_from_file(ascii_model)" in script
    assert "ASCII-only path" in script


def test_complete_bundle_contains_full_verified_accentor_model() -> None:
    from metrotrance.services.pronunciation import _ACCENTOR_SHA256, _ACCENTOR_SIZE

    model = ROOT / "metrotrance" / "resources" / "silero_stress" / "accentor.pt"
    assert model.is_file()
    assert model.stat().st_size == _ACCENTOR_SIZE
    import hashlib
    assert hashlib.sha256(model.read_bytes()).hexdigest() == _ACCENTOR_SHA256
