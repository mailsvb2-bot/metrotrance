from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.3.1"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
INSTALL_LOG = LOG_DIR / "install.log"
RUNTIME_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MetroTrance"
VENV_DIR = RUNTIME_ROOT / "venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
TEMP_DIR = RUNTIME_ROOT / "tmp"
PIP_CACHE_DIR = RUNTIME_ROOT / "pip-cache"
RUNTIME_APP = RUNTIME_ROOT / "app"
DOWNLOAD_DIR = RUNTIME_ROOT / "downloads"
LLAMA_DIR = RUNTIME_ROOT / "llama"
MODELS_DIR = RUNTIME_ROOT / "models"
LLAMA_SERVER = LLAMA_DIR / "llama-server.exe"

CORE_PACKAGES = [
    "fastapi>=0.116,<1",
    "uvicorn[standard]>=0.35,<1",
    "pydantic>=2.11,<3",
    "python-multipart>=0.0.20,<1",
    "httpx>=0.28,<1",
    "imageio-ffmpeg>=0.6,<1",
    "python-docx>=1.2,<2",
]
QWEN_PACKAGES = [
    "torch==2.11.0",
    "torchaudio==2.11.0",
    "qwen-tts==0.1.1",
    "soundfile>=0.13",
]
CHATTERBOX_PACKAGES = ["chatterbox-tts"]

MODEL_SPECS = {
    "fast": {
        "name": "Qwen3-4B Q4_K_M",
        "repo": "Qwen/Qwen3-4B-GGUF",
        "filename": "Qwen3-4B-Q4_K_M.gguf",
        "size_gb": 2.5,
    },
    "quality": {
        "name": "Qwen3-8B Q4_K_M",
        "repo": "Qwen/Qwen3-8B-GGUF",
        "filename": "Qwen3-8B-Q4_K_M.gguf",
        "size_gb": 5.03,
    },
    "max": {
        "name": "Qwen3-14B Q4_K_M",
        "repo": "Qwen/Qwen3-14B-GGUF",
        "filename": "Qwen3-14B-Q4_K_M.gguf",
        "size_gb": 9.0,
    },
}

REQUIRED_SOURCE_PATHS = [
    "pyproject.toml",
    ".env.example",
    "metrotrance/__init__.py",
    "metrotrance/__main__.py",
    "metrotrance/api.py",
    "metrotrance/config.py",
    "metrotrance/jobs.py",
    "metrotrance/models.py",
    "metrotrance/providers/__init__.py",
    "metrotrance/providers/qwen_tts.py",
    "metrotrance/providers/chatterbox_tts.py",
    "metrotrance/services/audio.py",
    "metrotrance/services/voice_quality.py",
    "metrotrance/services/audio_assets.py",
    "metrotrance/services/pronunciation.py",
    "metrotrance/services/pacing.py",
    "metrotrance/services/voice_profile.py",
    "metrotrance/services/local_llama.py",
    "metrotrance/services/script_writer.py",
    "metrotrance/services/studio_profile.py",
    "metrotrance/services/text_import.py",
    "metrotrance/profiles/studio_reference.json",
    "metrotrance/profiles/russian_pronunciation.json",
    "metrotrance/static/index.html",
    "metrotrance/static/app.js",
    "metrotrance/static/styles.css",
    "metrotrance_launcher.py",
]


def console(message: str = "") -> None:
    print(message, flush=True)


def log_header(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with INSTALL_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {message} ===\n")


def runtime_env() -> dict[str, str]:
    return {
        **os.environ,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONUTF8": "1",
        "TMP": str(TEMP_DIR),
        "TEMP": str(TEMP_DIR),
        "PIP_CACHE_DIR": str(PIP_CACHE_DIR),
    }


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with INSTALL_LOG.open("a", encoding="utf-8") as handle:
        handle.write("\n$ " + subprocess.list2cmdline(command) + "\n")
        handle.flush()
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_env(),
        )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Команда завершилась с кодом {completed.returncode}: "
            f"{subprocess.list2cmdline(command)}"
        )
    return completed.returncode


def tail(path: Path, lines: int = 55) -> str:
    if not path.exists():
        return "Журнал ещё не создан."
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def ensure_supported_python() -> None:
    version = sys.version_info
    valid_version = (version.major, version.minor) in {(3, 11), (3, 12)}
    is_64_bit = sys.maxsize > 2**32
    if not (valid_version and is_64_bit):
        raise RuntimeError(
            "Нужен 64-битный Python 3.11 или 3.12. "
            f"Сейчас используется: {sys.version.split()[0]}, "
            f"разрядность: {64 if is_64_bit else 32}."
        )


def validate_source_bundle() -> None:
    missing = [relative for relative in REQUIRED_SOURCE_PATHS if not (ROOT / relative).is_file()]
    if missing:
        joined = "\n  - ".join(missing)
        raise RuntimeError(
            "Папка MetroTrance неполная. Не хватает файлов:\n"
            f"  - {joined}\n\n"
            "Распакуйте полный архив MetroTrance 0.3.0 в эту папку с заменой файлов."
        )


def ensure_venv() -> None:
    if VENV_PY.exists():
        console(f"[1/8] Короткое окружение уже существует: {VENV_DIR}")
        return
    console(f"[1/8] Создаю короткое окружение: {VENV_DIR}")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "venv", str(VENV_DIR)])


def sync_runtime_source() -> None:
    console("[2/8] Копирую код в короткий рабочий путь...")
    if RUNTIME_APP.exists():
        shutil.rmtree(RUNTIME_APP)
    RUNTIME_APP.mkdir(parents=True, exist_ok=True)
    for name in ["pyproject.toml", "README.md", "LICENSE"]:
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, RUNTIME_APP / name)
    shutil.copytree(ROOT / "metrotrance", RUNTIME_APP / "metrotrance")


def install_core() -> None:
    console("[3/8] Обновляю pip, setuptools и wheel...")
    run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    console("[4/8] Устанавливаю API и интерфейс...")
    run([str(VENV_PY), "-m", "pip", "install", "--upgrade", *CORE_PACKAGES])
    run(
        [
            str(VENV_PY),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            "--no-deps",
            str(RUNTIME_APP),
        ],
        cwd=RUNTIME_APP,
    )
    if not (ROOT / ".env").exists():
        shutil.copy2(ROOT / ".env.example", ROOT / ".env")


def verify_core() -> None:
    console("[5/8] Проверяю базовый запуск...")
    code = (
        "import fastapi, uvicorn, metrotrance; "
        "from metrotrance.api import create_app; "
        "print(metrotrance.__version__)"
    )
    run([str(VENV_PY), "-c", code])


def install_qwen() -> bool:
    console("[6/8] Проверяю Qwen3-TTS...")
    verify_existing = run(
        [
            str(VENV_PY),
            "-c",
            "import torch, torchaudio, qwen_tts; "
            "assert torch.__version__.split('+')[0] == torchaudio.__version__.split('+')[0]",
        ],
        check=False,
    )
    if verify_existing == 0:
        console("Qwen3-TTS уже установлен.")
        return True
    code = run([str(VENV_PY), "-m", "pip", "install", "--upgrade", *QWEN_PACKAGES], check=False)
    if code != 0:
        console("Qwen3-TTS пока не установился. Интерфейс и сценарист всё равно будут работать.")
        return False
    verify = run(
        [
            str(VENV_PY),
            "-c",
            "import torch, torchaudio, qwen_tts; "
            "assert torch.__version__.split('+')[0] == torchaudio.__version__.split('+')[0]",
        ],
        check=False,
    )
    if verify != 0:
        console("Qwen3-TTS установлен неполностью. Подробности записаны в журнал.")
        return False
    console("Qwen3-TTS установлен успешно.")
    return True


def install_chatterbox() -> bool:
    console("Устанавливаю дополнительный Chatterbox...")
    code = run([str(VENV_PY), "-m", "pip", "install", "--upgrade", *CHATTERBOX_PACKAGES], check=False)
    if code != 0:
        console("Chatterbox не установился. Основным движком остаётся Qwen3-TTS.")
        return False
    return True


def physical_memory_gb() -> float:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024**3)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / (1024**3)
    except (AttributeError, ValueError, OSError):
        return 8.0


def select_model_tier(requested: str = "auto", ram_gb: float | None = None) -> str:
    requested = requested.strip().lower()
    if requested in MODEL_SPECS:
        return requested
    memory = physical_memory_gb() if ram_gb is None else ram_gb
    if memory >= 28:
        return "max"
    if memory >= 14:
        return "quality"
    return "fast"


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "MetroTrance-Installer/0.1.5"})
    with _opener().open(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download_file(url: str, destination: Path, label: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    existing = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "MetroTrance-Installer/0.1.5"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    console(f"Скачиваю {label}...")
    try:
        response = _opener().open(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and part.exists():
            part.replace(destination)
            return
        raise
    with response:
        status = int(getattr(response, "status", 200))
        if existing and status != 206:
            existing = 0
            part.unlink(missing_ok=True)
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        total = existing + content_length if content_length else 0
        mode = "ab" if existing else "wb"
        downloaded = existing
        last_percent = -5
        with part.open(mode) as handle:
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = int(downloaded * 100 / total)
                    if percent >= last_percent + 5:
                        console(f"  {percent}% ({downloaded / 1024**3:.2f} / {total / 1024**3:.2f} ГБ)")
                        last_percent = percent
                elif downloaded // (100 * 1024 * 1024) > (downloaded - len(chunk)) // (100 * 1024 * 1024):
                    console(f"  скачано {downloaded / 1024**3:.2f} ГБ")
    part.replace(destination)


def latest_llama_asset() -> tuple[str, str]:
    try:
        release = get_json("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest")
        for asset in release.get("assets", []):
            name = str(asset.get("name", ""))
            if name.endswith("-bin-win-cpu-x64.zip"):
                return str(asset["browser_download_url"]), name
    except Exception as exc:  # noqa: BLE001
        console(f"Не удалось определить свежую сборку llama.cpp: {exc}")
    name = "llama-b9637-bin-win-cpu-x64.zip"
    return f"https://github.com/ggml-org/llama.cpp/releases/download/b9637/{name}", name


def install_llama_binary() -> None:
    if LLAMA_SERVER.is_file():
        console("llama.cpp уже установлен.")
        return
    url, filename = latest_llama_asset()
    archive = DOWNLOAD_DIR / filename
    if not archive.is_file():
        download_file(url, archive, "локальный движок llama.cpp")
    extract_dir = TEMP_DIR / "llama-extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extract_dir)
    candidates = list(extract_dir.rglob("llama-server.exe"))
    if not candidates:
        raise RuntimeError("В архиве llama.cpp не найден llama-server.exe")
    source_dir = candidates[0].parent
    if LLAMA_DIR.exists():
        shutil.rmtree(LLAMA_DIR)
    shutil.copytree(source_dir, LLAMA_DIR)
    if not LLAMA_SERVER.is_file():
        raise RuntimeError("llama-server.exe не скопирован в рабочую папку")
    code = run([str(LLAMA_SERVER), "--version"], cwd=LLAMA_DIR, check=False)
    if code != 0:
        raise RuntimeError(
            "llama.cpp скачан, но не запускается на этой Windows. "
            "Подробности находятся в install.log."
        )


def model_url(spec: dict[str, object]) -> str:
    repo = str(spec["repo"])
    filename = str(spec["filename"])
    return f"https://huggingface.co/{repo}/resolve/main/{filename}?download=true"


def ensure_disk_space(required_gb: float) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(MODELS_DIR).free / (1024**3)
    if free < required_gb:
        raise RuntimeError(
            f"Недостаточно места на диске: свободно {free:.1f} ГБ, "
            f"нужно не менее {required_gb:.1f} ГБ."
        )


def install_model(tier: str) -> tuple[Path, dict[str, object]]:
    spec = MODEL_SPECS[tier]
    target = MODELS_DIR / str(spec["filename"])
    if target.is_file() and target.stat().st_size > 500 * 1024 * 1024:
        console(f"Модель уже загружена: {spec['name']}")
        return target, spec
    ensure_disk_space(float(spec["size_gb"]) + 1.5)
    download_file(model_url(spec), target, str(spec["name"]))
    if target.stat().st_size < 500 * 1024 * 1024:
        raise RuntimeError("Файл локальной модели скачался не полностью")
    return target, spec


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
    return result


def update_env(values: dict[str, str]) -> None:
    path = ROOT / ".env"
    existing = read_env(path)
    existing.update(values)
    preferred_order = [
        "METROTRANCE_HOST",
        "METROTRANCE_PORT",
        "METROTRANCE_OPEN_BROWSER",
        "METROTRANCE_DATA_DIR",
        "SCRIPT_PROVIDER",
        "LOCAL_LLAMA_URL",
        "LOCAL_LLAMA_BINARY",
        "LOCAL_LLAMA_MODEL",
        "LOCAL_LLAMA_MODEL_NAME",
        "LOCAL_LLAMA_CONTEXT",
        "LOCAL_LLAMA_THREADS",
        "LOCAL_LLAMA_STARTUP_TIMEOUT",
        "TTS_PROVIDER",
        "QWEN_TTS_MODEL",
        "QWEN_TTS_DEVICE",
        "CHATTERBOX_DEVICE",
        "AMBIENT_VOLUME",
        "PAUSE_SECONDS",
    ]
    defaults = read_env(ROOT / ".env.example")
    defaults.update(existing)
    lines: list[str] = []
    used: set[str] = set()
    for key in preferred_order:
        if key in defaults:
            lines.append(f"{key}={defaults[key]}")
            used.add(key)
    for key in sorted(defaults):
        if key not in used and not key.startswith(("OLLAMA_", "OPENAI_COMPATIBLE_")):
            lines.append(f"{key}={defaults[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def install_local_writer(requested_tier: str) -> None:
    console("[7/8] Устанавливаю локальный сценарист без Ollama...")
    ram = physical_memory_gb()
    tier = select_model_tier(requested_tier, ram)
    spec = MODEL_SPECS[tier]
    console(f"Оперативная память: {ram:.1f} ГБ")
    console(f"Выбран режим: {tier} — {spec['name']}")
    install_llama_binary()
    model_path, model_spec = install_model(tier)
    threads = max(1, (os.cpu_count() or 2) - 1)
    update_env(
        {
            "SCRIPT_PROVIDER": "llama_cpp",
            "LOCAL_LLAMA_URL": "http://127.0.0.1:8080/v1",
            "LOCAL_LLAMA_BINARY": LLAMA_SERVER.as_posix(),
            "LOCAL_LLAMA_MODEL": model_path.as_posix(),
            "LOCAL_LLAMA_MODEL_NAME": str(model_spec["name"]),
            "LOCAL_LLAMA_CONTEXT": "8192",
            "LOCAL_LLAMA_THREADS": str(threads),
            "LOCAL_LLAMA_STARTUP_TIMEOUT": "300",
        }
    )
    console("Локальный сценарист установлен. Ollama больше не нужна.")


def launch() -> int:
    return subprocess.call([str(VENV_PY), str(ROOT / "metrotrance_launcher.py")], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-only", action="store_true")
    parser.add_argument("--llm-only", action="store_true")
    parser.add_argument("--chatterbox-only", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--check-bundle-only", action="store_true")
    parser.add_argument("--model-tier", choices=["auto", "fast", "quality", "max"], default="auto")
    args = parser.parse_args()

    ensure_supported_python()
    log_header(f"MetroTrance Windows installer {VERSION}")
    console(f"MetroTrance {VERSION} — локальная установка")
    console(f"Папка программы: {ROOT}")
    console(f"Короткое окружение: {VENV_DIR}")
    console(f"Локальные модели: {MODELS_DIR}")
    console(f"Журнал: {INSTALL_LOG}")
    console()

    validate_source_bundle()
    console("Проверка комплекта файлов: успешно.")
    if args.check_bundle_only:
        return 0

    ensure_venv()
    sync_runtime_source()

    if args.chatterbox_only:
        if run([str(VENV_PY), "-c", "import metrotrance"], check=False) != 0:
            install_core()
            verify_core()
        install_chatterbox()
    elif args.tts_only:
        if run([str(VENV_PY), "-c", "import metrotrance"], check=False) != 0:
            install_core()
            verify_core()
        install_qwen()
    elif args.llm_only:
        install_core()
        verify_core()
        install_local_writer(args.model_tier)
    else:
        install_core()
        verify_core()
        install_qwen()
        install_local_writer(args.model_tier)

    console("[8/8] Установка завершена.")
    if args.no_launch or args.chatterbox_only:
        return 0
    console("Запускаю MetroTrance...")
    return launch()


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
