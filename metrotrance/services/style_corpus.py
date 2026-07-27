from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_CORPUS_DIR = Path(__file__).resolve().parent.parent / "resources" / "studio_corpus"
_MANIFEST_PATH = _CORPUS_DIR / "manifest.json"

_ALLOWED_FAMILIES = {
    "auto",
    "core_reference",
    "morning_reset",
    "evening_release",
    "evening_sleep",
    "agency_shift",
    "mind_unload",
}

# A small semantic layer is intentionally deterministic and local. The purpose is
# not to diagnose the user, but to pick the closest already-owned studio manner.
_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "morning_reset": (
        "утро", "утрен", "проснуться", "рабочий день", "начало дня", "ясность",
        "собраться", "настроиться", "туман", "дождливое утро",
    ),
    "evening_release": (
        "после работы", "вечер", "завершить день", "устал", "отпустить", "разряд",
        "расслабиться", "дорога домой", "восстановиться",
    ),
    "evening_sleep": (
        "сон", "уснуть", "заснуть", "сонлив", "перед сном", "ночь", "сумерк",
        "глубокий покой", "спокойный сон",
    ),
    "agency_shift": (
        "надо", "могу", "мотивац", "ресурс", "уверен", "выбор", "возможност",
        "внутренняя сила", "решиться", "действовать",
    ),
    "mind_unload": (
        "разгруз", "мысл", "перегруз", "голова", "мозг", "напряжение", "тревог",
        "навязчив", "внутренний шум", "успокоить ум",
    ),
}

# Fine-tuning around the common studio profile. These values remain conservative:
# the reference audio carries most of the manner, while parameters only nudge it.
_FAMILY_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "morning_reset": {
        "expressiveness": 3.0, "exaggeration": 0.015, "cfg_weight": -0.01,
        "temperature": 0.005, "pause_multiplier": -0.04,
    },
    "evening_release": {
        "expressiveness": -2.0, "exaggeration": -0.005, "cfg_weight": 0.01,
        "temperature": -0.01, "pause_multiplier": 0.08,
    },
    "evening_sleep": {
        "expressiveness": -7.0, "exaggeration": -0.025, "cfg_weight": 0.035,
        "temperature": -0.025, "pause_multiplier": 0.18,
    },
    "agency_shift": {
        "expressiveness": 6.0, "exaggeration": 0.035, "cfg_weight": -0.025,
        "temperature": 0.02, "pause_multiplier": -0.03,
    },
    "mind_unload": {
        "expressiveness": -4.0, "exaggeration": -0.015, "cfg_weight": 0.02,
        "temperature": -0.015, "pause_multiplier": 0.12,
    },
    "core_reference": {
        "expressiveness": 0.0, "exaggeration": 0.0, "cfg_weight": 0.0,
        "temperature": 0.0, "pause_multiplier": 0.0,
    },
}

_PHASE_PROMPT_MAP = {
    "opening": "opening",
    "tension": "settling",
    "story": "story",
    "insight": "story",
    "deep_body": "deep",
    "symbolic": "deep",
    "return": "return",
}


@dataclass(frozen=True)
class StyleFamilySelection:
    requested: str
    selected: str
    title: str
    source_recording: str
    reason: str
    scores: dict[str, float]

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "selected": self.selected,
            "title": self.title,
            "source_recording": self.source_recording,
            "reason": self.reason,
            "scores": self.scores,
        }


@lru_cache(maxsize=1)
def load_style_corpus() -> dict[str, Any]:
    if not _MANIFEST_PATH.is_file():
        return {"version": 0, "families": {}}
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data.get("families"), dict):
        raise ValueError("Некорректный manifest банка студийной манеры")
    return data


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def _score_family(text: str, family: str, manifest: dict[str, Any]) -> float:
    score = 0.0
    for phrase in _FAMILY_HINTS.get(family, ()):
        needle = _normalise(phrase)
        if needle and needle in text:
            score += 2.4 if " " in needle else 1.3
    meta = manifest.get("families", {}).get(family, {})
    for tag in meta.get("tags", []):
        needle = _normalise(str(tag))
        if needle and needle in text:
            score += 0.9
    # Gentle prior: mind-unload is the most generally useful calm studio manner.
    if family == "mind_unload":
        score += 0.15
    return round(score, 4)


def select_style_family(
    requested: str,
    *,
    goal: str = "",
    style: str = "",
    ending_state: str = "",
    extra_notes: str = "",
    source_text: str = "",
) -> StyleFamilySelection:
    requested = requested if requested in _ALLOWED_FAMILIES else "auto"
    manifest = load_style_corpus()
    families = manifest.get("families", {})

    if requested == "core_reference":
        return StyleFamilySelection(
            requested=requested,
            selected="core_reference",
            title="Исходный студийный эталон",
            source_recording="Новый рабочий день. Как запустить сердцевину спокойствия",
            reason="выбрано вручную",
            scores={},
        )
    if requested != "auto" and requested in families:
        meta = families[requested]
        return StyleFamilySelection(
            requested=requested,
            selected=requested,
            title=str(meta.get("title", requested)),
            source_recording=str(meta.get("source_recording", "")),
            reason="выбрано вручную",
            scores={},
        )

    text = _normalise(" ".join((goal, style, ending_state, extra_notes, source_text[:5000])))
    scores = {family: _score_family(text, family, manifest) for family in families}

    # The requested final state is more important than a passing image inside the
    # scenario. Without this bonus, a sleep practice mentioning a working day could
    # accidentally select an energetic morning/evening-release manner.
    ending = _normalise(ending_state)
    goal_text = _normalise(goal)
    if any(token in ending for token in ("сон", "уснуть", "заснуть", "сонлив")):
        scores["evening_sleep"] = round(scores.get("evening_sleep", 0.0) + 4.5, 4)
    if any(token in goal_text for token in ("уснуть", "заснуть", "сон", "бессон")):
        scores["evening_sleep"] = round(scores.get("evening_sleep", 0.0) + 2.5, 4)
    if any(token in goal_text for token in ("утро", "проснуться", "начать день")):
        scores["morning_reset"] = round(scores.get("morning_reset", 0.0) + 2.5, 4)
    if any(token in goal_text for token in ("разгруз", "поток мысл", "перегруз")):
        scores["mind_unload"] = round(scores.get("mind_unload", 0.0) + 2.5, 4)
    if not scores:
        return StyleFamilySelection(
            requested=requested,
            selected="core_reference",
            title="Исходный студийный эталон",
            source_recording="Новый рабочий день. Как запустить сердцевину спокойствия",
            reason="расширенный банк отсутствует",
            scores={},
        )
    selected = max(scores, key=lambda item: scores[item])
    # When the request carries no recognisable context, the original reference is
    # safer than pretending a specific session was semantically selected.
    if scores[selected] <= 0.2:
        return StyleFamilySelection(
            requested=requested,
            selected="core_reference",
            title="Исходный студийный эталон",
            source_recording="Новый рабочий день. Как запустить сердцевину спокойствия",
            reason="нет достаточно сильного тематического совпадения",
            scores=scores,
        )
    meta = families[selected]
    return StyleFamilySelection(
        requested=requested,
        selected=selected,
        title=str(meta.get("title", selected)),
        source_recording=str(meta.get("source_recording", "")),
        reason="автоматический выбор по цели, состоянию и тексту",
        scores=scores,
    )


def family_prompt_path(family: str, phase: str) -> Path | None:
    if family == "core_reference":
        return None
    manifest = load_style_corpus()
    meta = manifest.get("families", {}).get(family)
    if not meta:
        return None
    prompt_phase = _PHASE_PROMPT_MAP.get(phase, "story")
    prompt = meta.get("prompts", {}).get(prompt_phase, {})
    relative = prompt.get("file")
    if not relative:
        return None
    path = _CORPUS_DIR / str(relative)
    return path if path.is_file() else None


def family_adjustments(family: str) -> dict[str, float]:
    return dict(_FAMILY_ADJUSTMENTS.get(family, _FAMILY_ADJUSTMENTS["core_reference"]))


def style_corpus_public_dict() -> dict[str, Any]:
    manifest = load_style_corpus()
    result = {
        "version": manifest.get("version", 0),
        "privacy": manifest.get("privacy", ""),
        "families": {
            "core_reference": {
                "title": "Исходный студийный эталон",
                "source_recording": "Новый рабочий день. Как запустить сердцевину спокойствия",
                "prompt_count": 7,
            }
        },
    }
    for key, value in manifest.get("families", {}).items():
        result["families"][key] = {
            "title": value.get("title", key),
            "source_recording": value.get("source_recording", ""),
            "tags": value.get("tags", []),
            "prompt_count": len(value.get("prompts", {})),
        }
    return result
