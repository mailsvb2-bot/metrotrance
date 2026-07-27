from __future__ import annotations

from metrotrance import __version__

import windows_installer_core as _core


_core.VERSION = __version__

for _name in dir(_core):
    if not _name.startswith("__") and _name != "VERSION":
        globals()[_name] = getattr(_core, _name)

VERSION = __version__
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
