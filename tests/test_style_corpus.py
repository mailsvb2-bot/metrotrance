from __future__ import annotations

import json
import wave
from pathlib import Path

from metrotrance.services.performance_director import build_performance_plan, resolve_style_family
from metrotrance.services.style_corpus import load_style_corpus, style_corpus_public_dict


def test_private_style_corpus_contains_five_recording_families() -> None:
    corpus = load_style_corpus()
    assert set(corpus["families"]) == {
        "morning_reset",
        "evening_release",
        "evening_sleep",
        "agency_shift",
        "mind_unload",
    }
    assert all(len(item["prompts"]) == 5 for item in corpus["families"].values())


def test_every_style_prompt_is_pcm16_mono_24khz() -> None:
    corpus = load_style_corpus()
    root = Path(__file__).resolve().parent.parent / "metrotrance" / "resources" / "studio_corpus"
    for family in corpus["families"].values():
        for prompt in family["prompts"].values():
            path = root / prompt["file"]
            assert path.is_file()
            with wave.open(str(path), "rb") as wav:
                assert wav.getnchannels() == 1
                assert wav.getsampwidth() == 2
                assert wav.getframerate() == 24000
                assert 11.8 <= wav.getnframes() / wav.getframerate() <= 12.1


def test_auto_family_selection_uses_request_meaning() -> None:
    assert resolve_style_family("auto", goal="спокойно уснуть после тяжёлого вечера").selected == "evening_sleep"
    assert resolve_style_family("auto", goal="разгрузить мозг и остановить поток мыслей").selected == "mind_unload"
    assert resolve_style_family("auto", goal="перейти от надо к могу и почувствовать внутренний ресурс").selected == "agency_shift"
    assert resolve_style_family("auto", goal="собраться утром и начать рабочий день").selected == "morning_reset"


def test_selected_family_supplies_phase_specific_prompts() -> None:
    chunks = [
        "Утро начинается спокойно.",
        "Можно заметить остаточное напряжение.",
        "Однажды человек увидел дорогу.",
        "Перенесите внимание внутрь тела.",
        "Теперь можно мягко возвращаться.",
    ]
    selection = resolve_style_family("mind_unload", goal="разгрузить мозг")
    plan = build_performance_plan(chunks, style_family="mind_unload", selection=selection)
    assert all(cue.style_family == "mind_unload" for cue in plan)
    assert all(cue.prompt_path and "studio_corpus" in cue.prompt_path for cue in plan)
    assert plan[0].prompt_path != plan[-1].prompt_path


def test_public_corpus_does_not_expose_absolute_paths() -> None:
    public = style_corpus_public_dict()
    dumped = json.dumps(public, ensure_ascii=False)
    assert "studio_corpus" not in dumped
    assert "/mnt/" not in dumped
    assert public["families"]["morning_reset"]["prompt_count"] == 5
