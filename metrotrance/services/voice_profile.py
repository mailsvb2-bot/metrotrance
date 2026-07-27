from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from metrotrance.services.audio import ffmpeg_executable, wav_info


class VoiceProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceProfileInfo:
    duration_seconds: float
    sample_rate: int
    transcript_chars: int
    transcript_words: int


def normalize_transcript(value: str) -> str:
    """Keep spoken fillers and punctuation, but remove accidental whitespace noise."""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def validate_transcript(value: str) -> str:
    transcript = normalize_transcript(value)
    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", transcript)
    if len(transcript) < 40 or len(words) < 8:
        raise VoiceProfileError(
            "Нужна точная расшифровка образца: не менее 8 произнесённых слов. "
            "Без неё Qwen заметно хуже сохраняет голос и русскую артикуляцию."
        )
    return transcript


def prepare_reference_audio(
    source: Path,
    target: Path,
    *,
    min_seconds: float = 15.0,
    max_seconds: float = 60.0,
) -> VoiceProfileInfo:
    """Convert a reference to a conservative Qwen-friendly mono PCM WAV.

    We deliberately avoid denoising, compression and equalization because they can
    change speaker identity. Only channel count, sample rate and edge silence are
    normalized.
    """
    ffmpeg = ffmpeg_executable()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.new.wav")
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-af",
        (
            "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-50dB,"
            "areverse,"
            "silenceremove=start_periods=1:start_duration=0.20:start_threshold=-50dB,"
            "areverse"
        ),
        "-c:a",
        "pcm_s16le",
        str(temporary),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise VoiceProfileError(result.stderr.strip() or "Не удалось подготовить образец голоса")

    try:
        channels, sample_width, sample_rate, _, duration = wav_info(temporary)
        if channels != 1 or sample_width != 2:
            raise VoiceProfileError("Образец голоса не удалось преобразовать в моно PCM WAV")
        if duration < min_seconds:
            raise VoiceProfileError(
                f"Образец слишком короткий: {duration:.1f} с. Нужны {min_seconds:.0f}–{max_seconds:.0f} секунд."
            )
        if duration > max_seconds:
            raise VoiceProfileError(
                f"Образец слишком длинный: {duration:.1f} с. Нужны {min_seconds:.0f}–{max_seconds:.0f} секунд."
            )
        shutil.move(str(temporary), str(target))
        return VoiceProfileInfo(
            duration_seconds=duration,
            sample_rate=sample_rate,
            transcript_chars=0,
            transcript_words=0,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_voice_metadata(path: Path, info: VoiceProfileInfo, transcript: str) -> None:
    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", transcript)
    payload = {
        "duration_seconds": round(info.duration_seconds, 3),
        "sample_rate": info.sample_rate,
        "transcript_chars": len(transcript),
        "transcript_words": len(words),
        "x_vector_only_mode": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def assess_voice_profile(audio_path: Path, transcript: str) -> dict:
    """Return honest, non-neural suitability hints for a cloning reference."""
    warnings: list[str] = []
    try:
        channels, sample_width, sample_rate, _, duration = wav_info(audio_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "warnings": [f"Не удалось проверить образец: {exc}"]}
    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", transcript)
    wpm = len(words) * 60.0 / duration if duration > 0 else 0.0
    if wpm > 110:
        warnings.append(
            "Образец произнесён очень быстро. Для более живой трансовой речи лучше записать 25–45 секунд "
            "медленной, ясной речи без длинных э-э-э и обрывов."
        )
    elif wpm < 35:
        warnings.append("В образце слишком мало речи относительно длительности; модель получает мало артикуляционных переходов.")
    if duration < 20:
        warnings.append("Желательно использовать не менее 20 секунд чистой речи.")
    if len(words) < 25:
        warnings.append("В образце мало разных слов; персональный тембр и русская артикуляция могут переноситься нестабильно.")
    return {
        "ok": not warnings,
        "duration_seconds": round(duration, 2),
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bits": sample_width * 8,
        "transcript_words": len(words),
        "words_per_minute": round(wpm, 1),
        "warnings": warnings,
    }
