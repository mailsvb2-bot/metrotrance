from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from metrotrance.config import Settings

_START_LOCK = threading.Lock()
_SERVER_PROCESS: subprocess.Popen[bytes] | None = None


def _client(timeout: float) -> httpx.Client:
    # System proxy settings on old Windows installations sometimes intercept
    # localhost. Local inference must never go through a proxy.
    return httpx.Client(timeout=timeout, trust_env=False)


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def _port_from_url(url: str) -> int:
    parsed = urlsplit(url)
    return int(parsed.port or 8080)


def _base_without_v1(url: str) -> str:
    return url[:-3] if url.endswith("/v1") else url


def server_alive(url: str) -> bool:
    try:
        with _client(1.5) as client:
            response = client.get(f"{url}/models")
            return response.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def strip_reasoning(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = cleaned.replace("<think>", "").replace("</think>", "")
    return cleaned.strip()


def installation_status(settings: Settings) -> tuple[bool, str]:
    if not settings.local_llama_binary.is_file():
        return False, "Локальный сценарист не установлен: отсутствует llama-server.exe"
    if not settings.local_llama_model.is_file():
        return False, "Локальный сценарист не установлен: отсутствует файл модели"
    if server_alive(settings.local_llama_url):
        return True, f"Локальный сценарист работает: {settings.local_llama_model_name}"
    size_gb = settings.local_llama_model.stat().st_size / (1024**3)
    return True, (
        f"Локальный сценарист готов: {settings.local_llama_model_name} "
        f"({size_gb:.1f} ГБ), запустится автоматически"
    )


def ensure_server(settings: Settings) -> None:
    global _SERVER_PROCESS
    if server_alive(settings.local_llama_url):
        return

    ok, detail = installation_status(settings)
    if not ok:
        raise RuntimeError(detail)

    with _START_LOCK:
        if server_alive(settings.local_llama_url):
            return
        if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is None:
            process = _SERVER_PROCESS
        else:
            log_dir = settings.data_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "llama-server.log"
            port = _port_from_url(settings.local_llama_url)
            command = [
                str(settings.local_llama_binary),
                "--model",
                str(settings.local_llama_model),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ctx-size",
                str(settings.local_llama_context),
                "--threads",
                str(settings.local_llama_threads),
                "--jinja",
            ]
            log_handle = log_path.open("ab", buffering=0)
            try:
                process = subprocess.Popen(
                    command,
                    cwd=settings.local_llama_binary.parent,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=_creation_flags(),
                    close_fds=os.name != "nt",
                )
            except OSError as exc:
                raise RuntimeError(f"Не удалось запустить локальный сценарист: {exc}") from exc
            finally:
                log_handle.close()
            _SERVER_PROCESS = process
            (settings.data_dir / "logs" / "llama-server.pid").write_text(str(process.pid), encoding="ascii")

        deadline = time.monotonic() + settings.local_llama_startup_timeout
        while time.monotonic() < deadline:
            if server_alive(settings.local_llama_url):
                return
            return_code = process.poll()
            if return_code is not None:
                log_path = settings.data_dir / "logs" / "llama-server.log"
                tail = ""
                if log_path.exists():
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    tail = "\n".join(lines[-20:])
                raise RuntimeError(
                    f"Локальный сценарист завершился с кодом {return_code}.\n{tail}"
                )
            time.sleep(0.5)

    raise RuntimeError(
        "Локальная модель загружается слишком долго. Повторите создание транса; "
        "при следующем запуске модель может уже быть готова."
    )


def chat_completion(settings: Settings, messages: list[dict[str, str]], max_tokens: int) -> str:
    ensure_server(settings)
    payload = {
        "model": settings.local_llama_model_name,
        "messages": messages,
        "temperature": 0.72,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        with _client(1800.0) as client:
            response = client.post(f"{settings.local_llama_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ошибка локального сценариста: {exc}") from exc
    return strip_reasoning(str(content))


def shutdown_server(settings: Settings) -> None:
    """Release RAM before Qwen3-TTS is loaded. Only stops our own local server."""
    global _SERVER_PROCESS
    process = _SERVER_PROCESS
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=12)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
    _SERVER_PROCESS = None
    (settings.data_dir / "logs" / "llama-server.pid").unlink(missing_ok=True)
