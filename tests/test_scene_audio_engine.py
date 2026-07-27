from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from metrotrance.audio_engine.director import resolve_sound_plan
from metrotrance.audio_engine.scene_parser import SceneParser
from metrotrance.audio_engine.timeline_builder import build_sound_plan
from metrotrance.config import get_settings
from metrotrance.services.audio_assets import AudioAssetLibrary


def write_tone(path: Path, seconds: float = 6.0, rate: int = 12000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        frames = bytearray()
        for index in range(int(seconds * rate)):
            frames.extend(struct.pack("<h", int(math.sin(2 * math.pi * 180 * index / rate) * 1500)))
        wav.writeframes(frames)


def test_scene_parser_starts_stops_and_one_shots() -> None:
    cues = SceneParser().parse_segments([
        "Вы едете в вагоне метро.",
        "Вы выходите на улицу, начинается лёгкий дождь.",
        "Где-то далеко звучит клаксон.",
        "И теперь вы больше не слышите дождя.",
    ])
    values = [(item.action, item.category, item.segment_index) for item in cues]
    assert ("start", "metro", 0) in values
    assert ("start", "rain", 1) in values
    assert ("one_shot", "horn", 2) in values
    assert ("stop", "rain", 3) in values


def test_timeline_uses_real_segment_timing() -> None:
    plan = build_sound_plan(
        ["Вагон метро движется плавно.", "Вы выходите на улицу.", "Метро больше не слышно."],
        [5.0, 6.0, 4.0], [2.0, 3.0], 1.0, 21.0,
    )
    metro = [event for event in plan.events if event.category == "metro"]
    assert metro
    assert metro[0].start_seconds == 0.0
    assert metro[0].end_seconds is not None
    assert metro[0].end_seconds <= 21.0


def test_resolver_uses_only_reviewed_safe_assets(tmp_path: Path) -> None:
    settings = get_settings(tmp_path)
    library = AudioAssetLibrary(settings)
    source = tmp_path / "rain.wav"; write_tone(source)
    library.import_file(
        source, original_filename="rain.wav", kind="atmosphere", title="Без проверки",
        category="rain", license_basis="owned_exclusive", source_note="", rights_confirmed=True,
        content_reviewed=False, safe_for_trance=False,
    )
    plan = build_sound_plan(["Начинается дождь."], [5.0], [], 1.0, 7.0)
    unresolved, _ = resolve_sound_plan(plan, library, tmp_path / "job1", seed="a")
    assert not unresolved.events

    source2 = tmp_path / "rain-safe.wav"; write_tone(source2)
    safe = library.import_file(
        source2, original_filename="rain-safe.wav", kind="atmosphere", title="Безопасный дождь",
        category="rain", license_basis="owned_exclusive", source_note="", rights_confirmed=True,
        content_reviewed=True, safe_for_trance=True, loopable=True, recommended_volume_db=-33,
    )
    resolved, passport = resolve_sound_plan(plan, library, tmp_path / "job2", seed="a")
    assert resolved.events[0].asset_id == safe.id
    assert passport[0]["safe_for_trance"] is True
