from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from metrotrance.config import get_settings
from metrotrance.services.voice_quality import (
    analyze_pcm16_voice,
    load_voice_approval,
    save_voice_approval,
    synthesis_environment_fingerprint,
    voice_approval_status,
)


def _write_tone(path: Path, *, seconds: float = 20.0, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for index in range(int(seconds * rate)):
        value = int(6000 * math.sin(2 * math.pi * 120 * index / rate))
        frames.extend(int(value).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))


def _settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("METROTRANCE_DATA_DIR", str(tmp_path / "data"))
    settings = get_settings(tmp_path)
    _write_tone(settings.voice_audio)
    settings.voice_transcript.write_text(
        "Это точная тестовая расшифровка сохранённого образца голоса для проверки допуска.",
        encoding="utf-8",
    )
    settings.voice_metadata.write_text('{"duration_seconds":20}', encoding="utf-8")
    return settings


def test_voice_quality_report_is_explicitly_not_a_naturalness_score(tmp_path: Path) -> None:
    wav_path = tmp_path / "candidate.wav"
    _write_tone(wav_path)
    metrics = analyze_pcm16_voice(
        wav_path,
        expected_text="Добрый вечер. Это спокойная тестовая фраза.",
        speech_parts=[wav_path],
    )

    assert metrics.structural_ok
    assert metrics.duration_seconds == 20.0
    assert metrics.sample_rate == 24000
    assert metrics.expected_word_count > 0
    assert any("не доказывает живость" in item for item in metrics.limitations)


def test_voice_approval_is_bound_to_full_environment_and_candidate_snapshot(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    job_id = "abc123"
    candidate_path = settings.jobs_dir / job_id / "candidates" / "qwen_identity" / "voice.wav"
    _write_tone(candidate_path)
    fingerprint = synthesis_environment_fingerprint(settings)

    from metrotrance.services.voice_quality import sha256_file

    candidate = {
        "id": "qwen_identity",
        "blind_label": "Вариант A",
        "title": "Qwen",
        "provider": "qwen",
        "profile": "neutral",
        "expressiveness": 32,
        "seed": 11031,
        "environment_fingerprint": fingerprint,
        "raw_sha256": sha256_file(candidate_path),
        "metrics": {"structural_ok": True},
        "files": {"raw": str(candidate_path.relative_to(settings.jobs_dir / job_id))},
    }
    save_voice_approval(
        settings,
        job_id=job_id,
        candidate=candidate,
        ratings={"identity": 4, "naturalness": 4, "articulation": 5, "continuity": 4},
        listened_candidate_ids=["qwen_identity", "qwen_balanced"],
        required_candidate_ids=["qwen_identity", "qwen_balanced"],
    )

    assert load_voice_approval(settings)["candidate_id"] == "qwen_identity"
    assert voice_approval_status(settings)["approved"] is True
    assert (settings.voice_dir / "approved_candidate.wav").is_file()

    settings.voice_transcript.write_text("Расшифровка была изменена.", encoding="utf-8")
    assert load_voice_approval(settings) is None
    assert voice_approval_status(settings)["approved"] is False


def test_approval_rejects_less_bad_candidate_and_incomplete_listening(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    job_id = "abc123"
    candidate_path = settings.jobs_dir / job_id / "voice.wav"
    _write_tone(candidate_path)
    from metrotrance.services.voice_quality import sha256_file

    candidate = {
        "id": "qwen_identity",
        "title": "Qwen",
        "provider": "qwen",
        "profile": "neutral",
        "expressiveness": 32,
        "seed": 11031,
        "environment_fingerprint": synthesis_environment_fingerprint(settings),
        "raw_sha256": sha256_file(candidate_path),
        "metrics": {"structural_ok": True},
        "files": {"raw": "voice.wav"},
    }
    with pytest.raises(ValueError, match="прослушайте все"):
        save_voice_approval(
            settings,
            job_id=job_id,
            candidate=candidate,
            ratings={"identity": 5, "naturalness": 5, "articulation": 5, "continuity": 5},
            listened_candidate_ids=["qwen_identity"],
            required_candidate_ids=["qwen_identity", "qwen_balanced"],
        )

    with pytest.raises(ValueError, match="ниже 4/5"):
        save_voice_approval(
            settings,
            job_id=job_id,
            candidate=candidate,
            ratings={"identity": 5, "naturalness": 3, "articulation": 5, "continuity": 5},
            listened_candidate_ids=["qwen_identity"],
            required_candidate_ids=["qwen_identity"],
        )
