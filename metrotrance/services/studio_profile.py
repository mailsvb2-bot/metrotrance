from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "studio_reference.json"


@lru_cache(maxsize=1)
def load_studio_profile() -> dict[str, Any]:
    """Load the measured studio reference bundled with MetroTrance."""
    return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))


def recommended_word_range(duration_minutes: int) -> tuple[int, int]:
    minutes = max(1, duration_minutes)
    if minutes <= 1:
        return 70, 90
    profile = load_studio_profile()
    rates = profile["recommended_words_per_minute"]
    return int(minutes * rates["min"]), int(minutes * rates["max"])


def target_words(duration_minutes: int) -> int:
    low, high = recommended_word_range(duration_minutes)
    return round((low + high) / 2)


def pause_default(kind: str) -> float:
    values = load_studio_profile()["pause_seconds"]
    return float(values.get(kind, values["sentence"]))


def pause_cap(kind: str, base: float) -> float:
    caps = load_studio_profile()["pause_caps_seconds"]
    return max(base, float(caps.get(kind, base)))
