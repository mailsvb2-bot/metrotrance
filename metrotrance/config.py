from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _default_runtime_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "MetroTrance"
    return Path.home() / ".metrotrance"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    open_browser: bool
    data_dir: Path
    script_provider: str
    ollama_url: str
    ollama_model: str
    openai_url: str
    openai_api_key: str
    openai_model: str
    local_llama_url: str
    local_llama_binary: Path
    local_llama_model: Path
    local_llama_model_name: str
    local_llama_context: int
    local_llama_threads: int
    local_llama_startup_timeout: int
    tts_provider: str
    qwen_tts_model: str
    qwen_tts_device: str
    chatterbox_device: str
    ambient_volume: float
    pause_seconds: float

    @property
    def voice_dir(self) -> Path:
        return self.data_dir / "voice"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def voice_audio(self) -> Path:
        preferred = self.voice_dir / "reference.wav"
        if preferred.exists():
            return preferred
        candidates = sorted(self.voice_dir.glob("reference.*"))
        return candidates[0] if candidates else preferred

    @property
    def voice_transcript(self) -> Path:
        return self.voice_dir / "transcript.txt"

    @property
    def voice_metadata(self) -> Path:
        return self.voice_dir / "profile.json"

    @property
    def voice_quality_approval(self) -> Path:
        return self.voice_dir / "quality_approval.json"

    @property
    def pronunciation_dir(self) -> Path:
        return self.data_dir / "pronunciation"

    @property
    def pronunciation_dictionary(self) -> Path:
        return self.pronunciation_dir / "user_dictionary.json"

    @property
    def audio_assets_dir(self) -> Path:
        return self.data_dir / "audio_assets"


def get_settings(base_dir: Path | None = None) -> Settings:
    root = (base_dir or Path.cwd()).resolve()
    load_dotenv(root / ".env")
    data_raw = os.getenv("METROTRANCE_DATA_DIR", "./data")
    data_dir = Path(data_raw)
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "voice").mkdir(parents=True, exist_ok=True)
    (data_dir / "jobs").mkdir(parents=True, exist_ok=True)
    (data_dir / "pronunciation").mkdir(parents=True, exist_ok=True)
    (data_dir / "audio_assets" / "music").mkdir(parents=True, exist_ok=True)
    (data_dir / "audio_assets" / "atmosphere").mkdir(parents=True, exist_ok=True)
    (data_dir / "audio_assets" / "event").mkdir(parents=True, exist_ok=True)

    runtime_root = _default_runtime_root()
    binary_default = runtime_root / "llama" / "llama-server.exe"
    model_default = runtime_root / "models" / "Qwen3-4B-Q4_K_M.gguf"
    binary_raw = os.getenv("LOCAL_LLAMA_BINARY", "").strip()
    model_raw = os.getenv("LOCAL_LLAMA_MODEL", "").strip()
    cpu_count = max(1, os.cpu_count() or 1)

    return Settings(
        host=os.getenv("METROTRANCE_HOST", "127.0.0.1"),
        port=_int("METROTRANCE_PORT", 8765),
        open_browser=_bool("METROTRANCE_OPEN_BROWSER", True),
        data_dir=data_dir,
        script_provider=os.getenv("SCRIPT_PROVIDER", "llama_cpp").strip().lower(),
        ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        openai_url=os.getenv("OPENAI_COMPATIBLE_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
        openai_api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", "local"),
        openai_model=os.getenv("OPENAI_COMPATIBLE_MODEL", "qwen3"),
        local_llama_url=os.getenv("LOCAL_LLAMA_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
        local_llama_binary=Path(binary_raw).expanduser() if binary_raw else binary_default,
        local_llama_model=Path(model_raw).expanduser() if model_raw else model_default,
        local_llama_model_name=os.getenv("LOCAL_LLAMA_MODEL_NAME", "Qwen3-4B Q4_K_M"),
        local_llama_context=max(4096, min(_int("LOCAL_LLAMA_CONTEXT", 8192), 32768)),
        local_llama_threads=max(1, min(_int("LOCAL_LLAMA_THREADS", max(1, cpu_count - 1)), cpu_count)),
        local_llama_startup_timeout=max(30, min(_int("LOCAL_LLAMA_STARTUP_TIMEOUT", 300), 1200)),
        tts_provider=os.getenv("TTS_PROVIDER", "auto").strip().lower(),
        qwen_tts_model=os.getenv("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
        qwen_tts_device=os.getenv("QWEN_TTS_DEVICE", "auto").strip().lower(),
        chatterbox_device=os.getenv("CHATTERBOX_DEVICE", "auto").strip().lower(),
        ambient_volume=min(max(_float("AMBIENT_VOLUME", 0.11), 0.0), 0.5),
        pause_seconds=min(max(_float("PAUSE_SECONDS", 1.15), 0.1), 5.0),
    )
