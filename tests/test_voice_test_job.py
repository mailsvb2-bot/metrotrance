from __future__ import annotations

import math
import wave
from pathlib import Path
from types import SimpleNamespace

from metrotrance.config import get_settings
from metrotrance.jobs import JobManager
from metrotrance.models import JobRecord, TranceRequest


class _Prepared:
    def __init__(self, text: str) -> None:
        self.tts_text = text
        self.engine = "test"
        self.accents_added = 1
        self.yo_added = 0
        self.dictionary_hits = 0
        self.warning = None

    def report(self) -> dict:
        return {"tts_text": self.tts_text, "engine": self.engine}


class _Pronunciation:
    def __init__(self, settings) -> None:
        self.settings = settings

    def prepare_many(self, chunks):
        return [_Prepared(chunk) for chunk in chunks]


def _write_wav(path: Path, seconds: float = 3.0, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for index in range(int(seconds * rate)):
        value = int(5000 * math.sin(2 * math.pi * 120 * index / rate))
        frames.extend(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))


class _Provider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = []

    def health(self):
        return True, "ready"

    def synthesize_chunks(self, chunks, output_dir, reference_audio, transcript, performance=None):
        self.calls.append(
            {
                "chunks": list(chunks),
                "reference_audio": str(reference_audio),
                "performance": dict(performance or {}),
            }
        )
        paths = []
        for index, _ in enumerate(chunks, start=1):
            path = Path(output_dir) / f"chunk_{index:03d}.wav"
            _write_wav(path)
            paths.append(path)
        return paths


def test_voice_test_renders_candidates_and_never_passes_studio_audio_prompts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("METROTRANCE_DATA_DIR", str(tmp_path / "data"))
    settings = get_settings(tmp_path)
    _write_wav(settings.voice_audio, seconds=20.0)
    settings.voice_transcript.write_text("Точная тестовая расшифровка голоса.", encoding="utf-8")

    qwen = _Provider("qwen")
    chatterbox = _Provider("chatterbox")

    def fake_candidates(settings, requested=None):
        return [qwen if requested == "qwen" else chatterbox]

    monkeypatch.setattr("metrotrance.jobs.provider_candidates", fake_candidates)
    monkeypatch.setattr("metrotrance.jobs.RussianPronunciation", _Pronunciation)

    manager = JobManager(settings)
    request = TranceRequest(workflow_mode="voice_test")
    record = JobRecord.new("voice-test", request)
    manager._jobs[record.id] = record  # noqa: SLF001
    manager._save(record)  # noqa: SLF001
    job_dir = settings.jobs_dir / record.id
    job_dir.mkdir(parents=True, exist_ok=True)

    manager._run_voice_test(  # noqa: SLF001
        record.id,
        record,
        job_dir,
        settings.voice_audio,
        settings.voice_transcript.read_text(encoding="utf-8"),
    )

    completed = manager.get(record.id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.metadata["workflow_mode"] == "voice_test"
    assert len(completed.metadata["voice_candidates"]) == 3
    assert all(call["reference_audio"] == str(settings.voice_audio) for call in qwen.calls + chatterbox.calls)
    assert all(call["performance"].get("studio_reference_bank") is False for call in qwen.calls + chatterbox.calls)
    assert all(isinstance(call["performance"].get("seed"), int) for call in qwen.calls + chatterbox.calls)
    assert completed.metadata["blind_comparison"] is True
    assert all(item.get("blind_label") for item in completed.metadata["voice_candidates"])
    assert all("raw" in (item.get("files") or {}) for item in completed.metadata["voice_candidates"] if item.get("status") == "ready")
