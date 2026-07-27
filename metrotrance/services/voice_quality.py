from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from metrotrance.services import voice_quality_core as _core
from metrotrance.services.audio import normalize_wav_pcm16


def _read_pcm16_compatible(path: Path) -> tuple[int, int, int, int, bytes]:
    """Read WAV input and normalize every non-PCM16 stream before analysis."""
    native_error: Exception | None = None
    try:
        native = _read_native_pcm16(path)
        if native[1] == 2:
            return native
    except (wave.Error, EOFError) as exc:
        native_error = exc

    with tempfile.TemporaryDirectory(prefix="metrotrance-voice-quality-") as temp_dir:
        normalized = Path(temp_dir) / "normalized.wav"
        try:
            normalize_wav_pcm16(path, normalized)
            compatible = _read_native_pcm16(normalized)
            if compatible[1] != 2:
                raise ValueError("Нормализация WAV не создала PCM16 поток")
            return compatible
        except Exception as normalize_exc:  # noqa: BLE001
            cause = native_error or normalize_exc
            raise ValueError(
                f"Не удалось декодировать WAV для анализа: {normalize_exc}"
            ) from cause


for _name in dir(_core):
    if not _name.startswith("__") and _name != "_read_pcm16_compatible":
        globals()[_name] = getattr(_core, _name)

_core._read_pcm16_compatible = _read_pcm16_compatible
del _name
