from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def _accent_count(text: str) -> int:
    return unicodedata.normalize("NFD", text).count("\u0301")


def _project_root(value: str) -> Path:
    cleaned = os.path.expandvars(value.strip()).strip('"').rstrip('"')
    if not cleaned:
        raise ValueError("Project root is empty")
    return Path(cleaned).expanduser().resolve()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".installing")
    temporary.unlink(missing_ok=True)
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    root = _project_root(args.project_root)
    sys.path.insert(0, str(root))

    try:
        import metrotrance
        from metrotrance.config import get_settings
        from metrotrance.services.pronunciation import RussianPronunciation, plus_to_unicode

        imported_from = Path(metrotrance.__file__).resolve()
        expected_package = (root / "metrotrance").resolve()
        if imported_from != expected_package / "__init__.py" and expected_package not in imported_from.parents:
            raise RuntimeError(
                "Loaded a different MetroTrance package. "
                f"Expected under {expected_package}, got {imported_from}"
            )

        service = RussianPronunciation(get_settings(root))
        bundled = service.bundled_accentor_path
        ascii_model = service.runtime_accentor_path
        print(f"MetroTrance package: {imported_from}")
        print(f"Source model: {bundled}")
        print(f"ASCII model:  {ascii_model}")

        ok, reason = service._validate_model_file(bundled)  # noqa: SLF001
        if not ok:
            raise RuntimeError(f"Source model validation failed: {reason}")

        if os.name == "nt" and not str(ascii_model).isascii():
            raise RuntimeError(f"Chosen PyTorch model path is not ASCII-only: {ascii_model}")

        runtime_ok, _ = service._validate_model_file(ascii_model)  # noqa: SLF001
        if not runtime_ok:
            _atomic_copy(bundled, ascii_model)
        runtime_ok, runtime_reason = service._validate_model_file(ascii_model)  # noqa: SLF001
        if not runtime_ok:
            raise RuntimeError(f"ASCII model validation failed after copy: {runtime_reason}")

        accentor = service._load_accentor_from_file(ascii_model)  # noqa: SLF001
        sample = "Меня зовут Лева Королев. Я уже готов открыть все ваши замки любой сложности."
        raw = str(accentor(sample))
        print(f"Raw Silero output: {raw}")
        if "+" not in raw:
            raise RuntimeError(f"Silero returned no stress notation: {raw!r}")

        converted = plus_to_unicode(raw)
        if _accent_count(converted) <= 0 and "ё" not in converted.lower():
            raise RuntimeError(f"Stress conversion failed: {converted!r}")

        service._accentor = accentor  # noqa: SLF001
        service._accentor_failed = None  # noqa: SLF001
        service._cache.clear()  # noqa: SLF001
        result = service.prepare(sample)
        print(f"Engine: {result.engine}")
        print(f"Accents added: {result.accents_added}")
        print(f"Processed text: {result.tts_text}")
        if result.engine != "silero_stress" or result.accents_added <= 0:
            raise RuntimeError(
                "MetroTrance pronunciation pipeline did not use Silero Stress. "
                f"Engine={result.engine!r}, accents={result.accents_added}, warning={result.warning!r}"
            )

        health_path = ascii_model.parent / "health.json"
        health_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "project_root": str(root),
                    "metrotrance_import": str(imported_from),
                    "source_model": str(bundled),
                    "active_model": str(ascii_model),
                    "engine": result.engine,
                    "accents_added": result.accents_added,
                    "sample_output": result.tts_text,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Health report: {health_path}")
        print("Russian stress model is ready from an ASCII-only path.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("ERROR: Russian stress model repair failed.", file=sys.stderr)
        print(f"Reason: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
