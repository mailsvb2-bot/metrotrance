from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from metrotrance.services.style_corpus import (
    StyleFamilySelection,
    family_adjustments,
    family_prompt_path,
    select_style_family,
    style_corpus_public_dict,
)

_PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "studio_performance.json"
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "resources" / "studio_style"


@dataclass(frozen=True)
class PerformanceCue:
    index: int
    phase: str
    phase_title: str
    prompt_path: str | None
    expressiveness: int
    exaggeration: float
    cfg_weight: float
    temperature: float
    pause_multiplier: float
    direction: str
    source: str
    style_family: str = "core_reference"
    style_family_title: str = "Исходный студийный эталон"
    source_recording: str = ""

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["prompt_path"]:
            payload["prompt_file"] = Path(str(payload["prompt_path"])).name
        payload.pop("prompt_path", None)
        return payload


@lru_cache(maxsize=1)
def load_performance_profile() -> dict[str, Any]:
    return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))


def _keyword_phase(text: str, profile: dict[str, Any]) -> str | None:
    lowered = text.casefold()
    # Priority matters: a returning sentence may also mention the body or an image.
    for phase in ("return", "deep_body", "symbolic", "story", "insight", "tension"):
        for needle in profile.get("lexical_overrides", {}).get(phase, []):
            if str(needle).casefold() in lowered:
                return phase
    return None


def _position_phase(position: float, profile: dict[str, Any]) -> str:
    phases = profile["phases"]
    for phase in profile["phase_order"]:
        start, end = phases[phase]["position"]
        if float(start) <= position < float(end):
            return phase
    return str(profile["phase_order"][-1])


def classify_phase(text: str, index: int, total: int) -> tuple[str, str]:
    profile = load_performance_profile()
    # Preserve a dramatic frame even for a very short one-minute test.
    if index == 0:
        return "opening", "boundary"
    if total > 1 and index == total - 1:
        return "return", "boundary"
    keyword = _keyword_phase(text, profile)
    if keyword:
        return keyword, "keyword"
    position = (index + 0.5) / max(1, total)
    return _position_phase(position, profile), "position"


def build_performance_plan(
    chunks: Iterable[str],
    *,
    enabled: bool = True,
    user_expressiveness: int = 62,
    style_family: str = "core_reference",
    goal: str = "",
    style: str = "",
    ending_state: str = "",
    extra_notes: str = "",
    source_text: str = "",
    selection: StyleFamilySelection | None = None,
) -> list[PerformanceCue]:
    values = list(chunks)
    selection = selection or select_style_family(
        style_family,
        goal=goal,
        style=style,
        ending_state=ending_state,
        extra_notes=extra_notes,
        source_text=source_text,
    )
    if not values:
        return []
    profile = load_performance_profile()
    result: list[PerformanceCue] = []
    adjustments = family_adjustments(selection.selected)
    for index, text in enumerate(values):
        if enabled:
            phase, source = classify_phase(text, index, len(values))
        else:
            phase, source = "opening", "disabled"
        settings = profile["phases"][phase]
        prompt = None
        if enabled:
            prompt = family_prompt_path(selection.selected, phase)
            if prompt is None:
                prompt = _PROMPTS_DIR / settings["prompt"]
                if selection.selected != "core_reference":
                    source = f"{source}_family_fallback"
        if prompt is not None and not prompt.is_file():
            prompt = None
            source = f"{source}_prompt_missing"

        # User expressiveness remains meaningful, but the studio phase is the anchor.
        anchor = int(settings["expressiveness"] + adjustments["expressiveness"])
        blended = round(anchor * 0.72 + max(0, min(user_expressiveness, 100)) * 0.28)
        blended = max(0, min(100, blended))
        result.append(
            PerformanceCue(
                index=index,
                phase=phase,
                phase_title=str(settings["title"]),
                prompt_path=str(prompt) if prompt is not None else None,
                expressiveness=blended,
                exaggeration=max(0.25, min(0.90, float(settings["exaggeration"]) + adjustments["exaggeration"])),
                cfg_weight=max(0.15, min(0.65, float(settings["cfg_weight"]) + adjustments["cfg_weight"])),
                temperature=max(0.45, min(0.90, float(settings["temperature"]) + adjustments["temperature"])),
                pause_multiplier=max(0.70, min(1.65, float(settings["pause_multiplier"]) + adjustments["pause_multiplier"])),
                direction=str(settings["direction"]),
                source=source,
                style_family=selection.selected,
                style_family_title=selection.title,
                source_recording=selection.source_recording,
            )
        )
    return result


def resolve_style_family(
    requested: str,
    *,
    goal: str = "",
    style: str = "",
    ending_state: str = "",
    extra_notes: str = "",
    source_text: str = "",
) -> StyleFamilySelection:
    return select_style_family(
        requested,
        goal=goal,
        style=style,
        ending_state=ending_state,
        extra_notes=extra_notes,
        source_text=source_text,
    )


def prompt_paths(plan: Iterable[PerformanceCue]) -> list[str | None]:
    return [cue.prompt_path for cue in plan]


def provider_payload(plan: Iterable[PerformanceCue]) -> list[dict[str, Any]]:
    return [asdict(cue) for cue in plan]


def apply_pause_shape(base_pauses: list[float], plan: list[PerformanceCue]) -> list[float]:
    if not base_pauses:
        return []
    result: list[float] = []
    for index, pause in enumerate(base_pauses):
        cue = plan[min(index, len(plan) - 1)] if plan else None
        multiplier = cue.pause_multiplier if cue is not None else 1.0
        # Keep speech pauses bounded. Explicit long pauses have already been authored
        # and must not grow without limit merely because a phase is deep.
        maximum = 16.0 if pause >= 5.0 else 8.0
        result.append(round(min(maximum, max(0.25, pause * multiplier)), 3))
    return result


def profile_public_dict() -> dict[str, Any]:
    profile = load_performance_profile()
    public = {
        "id": profile["id"],
        "name": profile["name"],
        "source": profile["source"],
        "principle": profile["principle"],
        "phases": {},
        "style_corpus": style_corpus_public_dict(),
    }
    for key, value in profile["phases"].items():
        public["phases"][key] = {
            "title": value["title"],
            "direction": value["direction"],
            "measured": value["measured"],
        }
    return public
