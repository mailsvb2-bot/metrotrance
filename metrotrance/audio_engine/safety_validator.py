from __future__ import annotations

import re
import subprocess
from pathlib import Path

from metrotrance.services.audio import ffmpeg_executable
from .models import SafetyFinding, SafetyReport

_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _duration_from_stderr(text: str) -> float:
    match = _DURATION_RE.search(text)
    if not match:
        return 0.0
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def validate_rendered_audio(path: Path, *, expected_seconds: float | None = None) -> SafetyReport:
    command = [
        ffmpeg_executable(), "-hide_banner", "-i", str(path),
        "-af", "volumedetect,silencedetect=noise=-55dB:d=20", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    duration = _duration_from_stderr(text)
    max_match = _MAX_RE.search(text)
    mean_match = _MEAN_RE.search(text)
    max_db = float(max_match.group(1)) if max_match else None
    mean_db = float(mean_match.group(1)) if mean_match else None

    starts = [float(value) for value in _SILENCE_START_RE.findall(text)]
    ends = [float(value) for value in _SILENCE_END_RE.findall(text)]
    longest = 0.0
    for start, end in zip(starts, ends, strict=False):
        longest = max(longest, max(0.0, end - start))

    findings: list[SafetyFinding] = []
    if result.returncode != 0:
        findings.append(SafetyFinding("ffmpeg_probe_failed", "error", "Не удалось проверить итоговый аудиофайл"))
    if duration <= 1.0:
        findings.append(SafetyFinding("empty_or_short", "error", "Итоговый файл пуст или слишком короткий"))
    if max_db is not None and max_db > -1.0:
        findings.append(SafetyFinding("peak_too_high", "warning", f"Пик {max_db:.1f} dBFS выше безопасного ориентира −1 dBFS"))
    if max_db is not None and max_db >= 0.0:
        findings.append(SafetyFinding("clipping_risk", "error", "Обнаружен риск цифрового клиппинга"))
    if mean_db is not None and mean_db > -12.0:
        findings.append(SafetyFinding("too_loud", "warning", "Средняя громкость необычно высока для транса"))
    if longest > 60.0:
        findings.append(SafetyFinding("unexpected_long_silence", "warning", f"Обнаружена тишина длительностью {longest:.1f} с"))
    if expected_seconds and duration and abs(duration - expected_seconds) > max(8.0, expected_seconds * 0.08):
        findings.append(SafetyFinding("duration_mismatch", "warning", "Фактическая длительность заметно отличается от расчётной"))
    findings.append(
        SafetyFinding(
            "manual_content_review_required",
            "info",
            "Автоматика проверяет уровни и тишину, но не может надёжно распознать сирены, чужие голоса или пугающие события; исходники должны быть одобрены вручную.",
        )
    )
    ok = not any(item.severity == "error" for item in findings)
    return SafetyReport(ok, duration, max_db, mean_db, longest, tuple(findings))
