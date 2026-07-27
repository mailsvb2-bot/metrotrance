from __future__ import annotations

from collections import defaultdict

from .models import SceneCue, SoundEvent, SoundPlan
from .scene_parser import SceneParser

_DEFAULT_DB = {
    "metro": -32.0,
    "rain": -32.0,
    "city": -35.0,
    "forest": -35.0,
    "birds": -38.0,
    "ocean": -33.0,
    "cafe": -36.0,
    "room": -39.0,
    "fire": -37.0,
    "stream": -35.0,
    "horn": -42.0,
    "car_passing": -39.0,
    "doors": -40.0,
    "footsteps": -41.0,
}


def segment_starts(durations: list[float], pauses: list[float], edge: float) -> list[float]:
    starts: list[float] = []
    cursor = max(0.0, edge)
    for index, duration in enumerate(durations):
        starts.append(cursor)
        cursor += max(0.0, duration)
        if index < len(pauses):
            cursor += max(0.0, pauses[index])
    return starts


def build_sound_plan(
    texts: list[str],
    durations: list[float],
    pauses: list[float],
    edge_silence_seconds: float,
    total_duration: float,
    *,
    mode: str = "auto_scene",
) -> SoundPlan:
    if mode != "auto_scene":
        return SoundPlan(total_duration, mode)
    if len(texts) != len(durations):
        raise ValueError("Текстовые и голосовые фрагменты не совпадают")

    starts = segment_starts(durations, pauses, edge_silence_seconds)
    cues = SceneParser().parse_segments(texts)
    by_segment: dict[int, list[SceneCue]] = defaultdict(list)
    for cue in cues:
        by_segment[cue.segment_index].append(cue)

    active: dict[str, tuple[float, int]] = {}
    events: list[SoundEvent] = []
    for index, start in enumerate(starts):
        for cue in by_segment.get(index, []):
            if cue.action == "start":
                if cue.category not in active:
                    active[cue.category] = (max(0.0, start - 1.5), index)
            elif cue.action == "stop":
                opened = active.pop(cue.category, None)
                if opened:
                    event_start, source_index = opened
                    end = min(total_duration, start + 1.5)
                    if end - event_start >= 1.0:
                        events.append(
                            SoundEvent(
                                "ambience", cue.category, event_start, end,
                                _DEFAULT_DB.get(cue.category, -35.0), 5.0, 7.0, source_index,
                            )
                        )
            elif cue.action == "one_shot":
                events.append(
                    SoundEvent(
                        "one_shot", cue.category, min(total_duration, start + 0.8), None,
                        _DEFAULT_DB.get(cue.category, -41.0), 0.35, 1.0, index,
                    )
                )

    for category, (start, source_index) in active.items():
        end = total_duration
        if end - start >= 1.0:
            events.append(
                SoundEvent(
                    "ambience", category, start, end,
                    _DEFAULT_DB.get(category, -35.0), 6.0, 10.0, source_index,
                )
            )

    events.sort(key=lambda item: (item.start_seconds, item.type, item.category))
    warnings: list[str] = []
    if not events:
        warnings.append("Сценический анализ не нашёл звуковых сцен; сохранён выбранный основной фон.")
    return SoundPlan(total_duration, mode, tuple(events), tuple(warnings))
