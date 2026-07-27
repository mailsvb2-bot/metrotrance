from __future__ import annotations

import os
from pathlib import Path

from metrotrance import __version__

import windows_installer_core as _core


# Keep one canonical product version while preserving the public installer module
# and its source-level contracts used by release and packaging checks.
_core.VERSION = __version__

for _name in dir(_core):
    if not _name.startswith("__") and _name != "VERSION":
        globals()[_name] = getattr(_core, _name)

VERSION = __version__
RUNTIME_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MetroTrance"
TEMP_DIR = RUNTIME_ROOT / "tmp"
PIP_CACHE_DIR = RUNTIME_ROOT / "pip-cache"
VENV_DIR = RUNTIME_ROOT / "venv"
RUNTIME_APP = RUNTIME_ROOT / "app"
CORE_PACKAGES = _core.CORE_PACKAGES
QWEN_PACKAGES = _core.QWEN_PACKAGES
REQUIRED_SOURCE_PATHS = _core.REQUIRED_SOURCE_PATHS


def validate_source_bundle() -> None:
    _core.validate_source_bundle()


del _name


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        console("\nУстановка прервана пользователем.")
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001
        console()
        console("ОШИБКА УСТАНОВКИ")
        console(str(exc))
        console(f"Журнал: {INSTALL_LOG}")
        console("Последние строки журнала:")
        console("-" * 72)
        console(tail(INSTALL_LOG))
        console("-" * 72)
        raise SystemExit(1)
