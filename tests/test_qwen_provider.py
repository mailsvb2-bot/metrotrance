from pathlib import Path
from types import SimpleNamespace

import pytest

from metrotrance.providers.qwen_tts import QwenTTSError, QwenTTSProvider


class FakeModel:
    def __init__(self):
        self.calls = []

    def create_voice_clone_prompt(self, **kwargs):
        self.calls.append(kwargs)
        return {"prompt": len(self.calls)}


def test_voice_prompt_never_uses_x_vector_only(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"voice")
    provider = QwenTTSProvider(SimpleNamespace())
    model = FakeModel()
    provider._load = lambda: model

    prompt = provider._voice_prompt(reference, "Это достаточно длинная точная расшифровка образца голоса.")

    assert prompt == {"prompt": 1}
    assert model.calls[0]["x_vector_only_mode"] is False


def test_voice_prompt_rejects_missing_transcript(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"voice")
    provider = QwenTTSProvider(SimpleNamespace())
    with pytest.raises(QwenTTSError):
        provider._voice_prompt(reference, "")


def test_prompt_cache_is_invalidated_when_transcript_changes(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"voice")
    provider = QwenTTSProvider(SimpleNamespace())
    model = FakeModel()
    provider._load = lambda: model

    provider._voice_prompt(reference, "Первая точная расшифровка выбранного образца голоса.")
    provider._voice_prompt(reference, "Вторая точная расшифровка выбранного образца голоса.")

    assert len(model.calls) == 2
