from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "data" / "logs"
SERVER_LOG = LOG_DIR / "server.log"
PID_FILE = LOG_DIR / "server.pid"
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def endpoint() -> tuple[str, int, str]:
    values = load_env_file(ROOT / ".env")
    host = os.getenv("METROTRANCE_HOST", values.get("METROTRANCE_HOST", "127.0.0.1"))
    raw_port = os.getenv("METROTRANCE_PORT", values.get("METROTRANCE_PORT", "8765"))
    try:
        port = int(raw_port)
    except ValueError:
        port = 8765
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return host, port, f"http://{browser_host}:{port}"


def _read_url(url: str, path: str, timeout: float) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        f"{url}{path}",
        headers={"Cache-Control": "no-cache", "User-Agent": "MetroTrance-Launcher/0.2.1.1"},
    )
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            return int(response.status), response.read(256 * 1024), str(response.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(32 * 1024), str(exc.headers.get("Content-Type", ""))


def tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def readiness(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Fast startup probe that never calls the slow dependency health check."""
    errors: list[str] = []
    try:
        status, body, _ = _read_url(url, "/api/ready", timeout)
        if status == 200:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict) and payload.get("product") == "MetroTrance":
                return True, str(payload.get("version", "unknown"))
        elif status not in {404, 405}:
            errors.append(f"/api/ready: HTTP {status}")
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        errors.append(f"/api/ready: {exc}")

    # Compatibility with a MetroTrance 0.1.3 process that may still be running.
    # Its /api/health is intentionally not used because it checks Ollama and can
    # take longer than the launcher's per-request timeout.
    try:
        status, body, content_type = _read_url(url, "/", timeout)
        text = body.decode("utf-8", errors="ignore")
        if status == 200 and "MetroTrance" in text and ("text/html" in content_type or "<html" in text.lower()):
            return True, "0.1.3+"
        if status == 200:
            errors.append("На порту отвечает другое веб-приложение")
    except (OSError, urllib.error.URLError) as exc:
        errors.append(f"/: {exc}")

    return False, "; ".join(errors[-2:]) or "сервер пока не отвечает"


def tail(path: Path, lines: int = 45) -> str:
    if not path.exists():
        return "Журнал сервера ещё не создан."
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:]) or "Журнал пуст."


def open_ui(url: str) -> bool:
    try:
        if os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        return bool(webbrowser.open(url, new=2))
    except Exception:
        try:
            return bool(webbrowser.open(url, new=2))
        except Exception:
            return False


def import_check() -> tuple[bool, str]:
    command = [
        sys.executable,
        "-c",
        "import fastapi, uvicorn, metrotrance; from metrotrance.api import create_app; print(metrotrance.__version__)",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    detail = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode == 0, detail


def child_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def start_server() -> subprocess.Popen[bytes]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["METROTRANCE_OPEN_BROWSER"] = "0"
    log_handle = SERVER_LOG.open("ab", buffering=0)
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "metrotrance"],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=child_creation_flags(),
            close_fds=os.name != "nt",
        )
    finally:
        log_handle.close()
    PID_FILE.write_text(str(process.pid), encoding="ascii")
    return process


def pause_on_windows() -> None:
    if os.name == "nt" and sys.stdin and sys.stdin.isatty():
        try:
            input("\nНажмите Enter, чтобы закрыть это окно...")
        except EOFError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Надёжный запуск MetroTrance")
    parser.add_argument("--check-only", action="store_true", help="только проверить окружение")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--wait-seconds", type=int, default=45)
    args = parser.parse_args()

    os.chdir(ROOT)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    host, port, url = endpoint()
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host

    print("MetroTrance — проверка запуска")
    print(f"Папка: {ROOT}")
    print(f"Интерфейс: {url}")

    ok, detail = import_check()
    if not ok:
        print("\nОШИБКА: окружение установлено не полностью.")
        print(detail or "Не удалось импортировать компоненты MetroTrance.")
        print("\nЗапустите INSTALL_WINDOWS.bat повторно.")
        pause_on_windows()
        return 2
    print(f"Python-окружение исправно: {detail.splitlines()[0] if detail else 'да'}")

    alive, version = readiness(url)
    if alive:
        print(f"MetroTrance уже работает, версия {version}.")
        if not args.no_browser and not open_ui(url):
            print(f"Откройте вручную: {url}")
        return 0

    if args.check_only:
        print("Проверка окружения пройдена. Сервер сейчас не запущен.")
        return 0

    if tcp_port_open(probe_host, port):
        print(f"\nОШИБКА: порт {port} занят другим процессом, но MetroTrance на нём не распознана.")
        print(f"Проверка: {version}")
        print("Закройте программу, которая использует этот порт, либо измените METROTRANCE_PORT в .env.")
        pause_on_windows()
        return 5

    print("Запускаю локальный API...")
    process = start_server()
    deadline = time.monotonic() + max(10, args.wait_seconds)
    last_detail = ""

    while time.monotonic() < deadline:
        alive, version = readiness(url)
        last_detail = version
        if alive:
            print(f"Готово. MetroTrance {version} запущена.")
            if not args.no_browser and not open_ui(url):
                print(f"Браузер не открылся автоматически. Откройте: {url}")
            return 0
        return_code = process.poll()
        if return_code is not None:
            print(f"\nОШИБКА: сервер завершился с кодом {return_code}.")
            print("\nПоследние строки журнала:")
            print("-" * 68)
            print(tail(SERVER_LOG))
            print("-" * 68)
            print(f"Полный журнал: {SERVER_LOG}")
            pause_on_windows()
            return 3
        time.sleep(0.35)

    print("\nОШИБКА: сервер запущен как процесс, но HTTP-интерфейс не прошёл проверку.")
    print(f"Последняя причина проверки: {last_detail}")
    print("\nПоследние строки журнала:")
    print("-" * 68)
    print(tail(SERVER_LOG))
    print("-" * 68)
    print(f"Полный журнал: {SERVER_LOG}")
    print(f"Попробуйте открыть вручную: {url}")
    pause_on_windows()
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
