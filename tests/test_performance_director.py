from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from metrotrance.providers.chatterbox_tts import ChatterboxTTSProvider
from metrotrance.services.performance_director import (
    apply_pause_shape,
    build_performance_plan,
    profile_public_dict,
    prompt_paths,
    provider_payload,
)


def test_studio_plan_uses_phase_specific_reference_bank() -> None:
    chunks = [
        "Утро постепенно становится яснее.",
        "Напряжение можно заметить и не усиливать.",
        "Однажды в старом городе жил мастер.",
        "И тогда становится ясно самое важное.",
        "Перенесите внимание внутрь тела и почувствуйте дыхание.",
        "Представьте символ света и внутренний компас.",
        "Теперь можно мягко возвращаться к окружающему пространству.",
    ]
    plan = build_performance_plan(chunks, user_expressiveness=62)

    assert [cue.phase for cue in plan] == [
        "opening",
        "tension",
        "story",
        "insight",
        "deep_body",
        "symbolic",
        "return",
    ]
    assert all(cue.prompt_path and Path(cue.prompt_path).is_file() for cue in plan)
    assert len(set(prompt_paths(plan))) == 7
    assert plan[2].exaggeration > plan[4].exaggeration


def test_phase_pause_shape_does_not_time_stretch_voice() -> None:
    plan = build_performance_plan(["Вступление.", "Дыхание и внимание внутрь тела.", "Возвращайтесь."], user_expressiveness=62)
    pauses = apply_pause_shape([2.0, 6.0], plan)
    assert pauses[0] > 0
    assert pauses[1] <= 16.0
    assert len(pauses) == 2


def test_public_profile_does_not_expose_absolute_paths() -> None:
    public = profile_public_dict()
    assert public["id"] == "sergey_studio_performance_v1"
    assert "prompt_path" not in str(public)


def test_chatterbox_uses_only_clean_reference_for_every_chunk(tmp_path, monkeypatch) -> None:
    calls: list[dict] = []

    class FakeModel:
        sr = 24000

        def generate(self, text, **kwargs):
            calls.append({"text": text, **kwargs})
            return object()

    fake_torchaudio = ModuleType("torchaudio")

    def fake_save(path, wav, sample_rate):
        del wav, sample_rate
        Path(path).write_bytes(b"RIFFfake")

    fake_torchaudio.save = fake_save
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    provider = ChatterboxTTSProvider(SimpleNamespace(chatterbox_device="cpu"))
    monkeypatch.setattr(provider, "_load", lambda: FakeModel())

    chunks = ["Однажды началась история.", "Теперь можно возвращаться."]
    plan = build_performance_plan(chunks, user_expressiveness=62)
    reference = tmp_path / "clean_voice.wav"
    reference.write_bytes(b"RIFFclean")

    provider.synthesize_chunks(
        chunks,
        tmp_path / "out",
        reference,
        "точная расшифровка",
        performance={
            "profile": "studio_melodic",
            "expressiveness": 62,
            "cues": provider_payload(plan),
            "reference_audio_paths": prompt_paths(plan),
        },
    )

    assert len(calls) == 2
    assert calls[0]["audio_prompt_path"] == str(reference)
    assert calls[1]["audio_prompt_path"] == str(reference)
    assert calls[0]["temperature"] != calls[1]["temperature"]
