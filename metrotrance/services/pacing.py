from __future__ import annotations

from dataclasses import dataclass

from metrotrance.services.studio_profile import pause_cap


@dataclass(frozen=True)
class PacingPlan:
    tempo: float
    pause_seconds: tuple[float, ...]
    edge_silence_seconds: float
    target_seconds: float
    expected_seconds: float
    feasible: bool
    warning: str | None = None


def preferred_tempo(style: str, duration_minutes: int) -> float:
    """Compatibility value: post-synthesis speech time-stretch is disabled."""
    del style, duration_minutes
    return 1.0


def _pause_cap(base: float, kind: str, profile: str) -> float:
    if kind == "explicit_exact":
        return base
    if profile == "natural":
        natural_caps = {
            "sentence": 1.4,
            "question": 2.0,
            "ellipsis": 2.8,
            "paragraph": 4.5,
            "explicit_short": 1.5,
            "explicit_semantic": 3.0,
            "explicit_deep": 6.0,
            "explicit_long": 8.0,
            "explicit_integration": 10.0,
        }
        return max(base, natural_caps.get(kind, base))
    return pause_cap(kind, base)


def _pause_weight(kind: str) -> float:
    return {
        "sentence": 0.7,
        "question": 1.0,
        "ellipsis": 1.25,
        "paragraph": 2.0,
        "explicit_short": 0.8,
        "explicit_semantic": 1.5,
        "explicit_deep": 2.2,
        "explicit_long": 2.5,
        "explicit_integration": 3.2,
        "explicit_exact": 0.0,
    }.get(kind, 1.0)


def _scale_pauses_to_budget(
    base_pauses: list[float],
    pause_kinds: list[str],
    budget: float,
    profile: str,
) -> tuple[list[float], float]:
    if not base_pauses:
        return [], max(0.0, budget)

    pauses = [max(0.0, value) for value in base_pauses]
    current = sum(pauses)
    if budget <= current:
        # Explicit numeric pauses are promises made by the author and are not shrunk.
        fixed = sum(value for value, kind in zip(pauses, pause_kinds, strict=False) if kind == "explicit_exact")
        scalable_indices = [i for i, kind in enumerate(pause_kinds) if kind != "explicit_exact"]
        scalable_total = sum(pauses[i] for i in scalable_indices)
        remaining = max(0.0, budget - fixed)
        factor = min(1.0, remaining / scalable_total) if scalable_total > 0 else 1.0
        factor = max(0.45, factor)
        for index in scalable_indices:
            pauses[index] *= factor
        return pauses, 0.0

    remaining = budget - current
    caps = [_pause_cap(base, kind, profile) for base, kind in zip(pauses, pause_kinds, strict=False)]
    active = {
        index
        for index, (value, cap, kind) in enumerate(zip(pauses, caps, pause_kinds, strict=False))
        if kind != "explicit_exact" and cap > value + 1e-9
    }

    while active and remaining > 1e-6:
        weights = {index: max(0.1, _pause_weight(pause_kinds[index])) for index in active}
        weight_sum = sum(weights.values()) or float(len(active))
        consumed = 0.0
        saturated: set[int] = set()
        for index in list(active):
            share = remaining * (weights[index] / weight_sum)
            room = caps[index] - pauses[index]
            addition = min(room, share)
            pauses[index] += addition
            consumed += addition
            if room - addition <= 1e-6:
                saturated.add(index)
        remaining -= consumed
        active -= saturated
        if consumed <= 1e-9:
            break

    return pauses, max(0.0, remaining)


def build_pacing_plan(
    raw_speech_seconds: float,
    base_pauses: list[float] | int | None = None,
    duration_minutes: int = 10,
    style: str = "мягкий, спокойный",
    pause_kinds: list[str] | None = None,
    fit_to_duration: bool = True,
    pacing_profile: str = "studio_reference",
    *,
    chunk_count: int | None = None,
) -> PacingPlan:
    """Build a pause-only timing plan without altering the synthesized voice."""
    del style
    target = float(max(1, duration_minutes) * 60)
    edge = 0.8 if duration_minutes <= 1 else 1.2

    if chunk_count is not None:
        base_pauses = chunk_count
    if base_pauses is None:
        base_pauses = 1

    if isinstance(base_pauses, int):
        gap_count = max(0, base_pauses - 1)
        pause_values = [0.9] * gap_count
        kinds = ["sentence"] * gap_count
    else:
        pause_values = [max(0.0, value) for value in base_pauses]
        kinds = list(pause_kinds or ["sentence"] * len(pause_values))
        if len(kinds) < len(pause_values):
            kinds.extend(["sentence"] * (len(pause_values) - len(kinds)))

    natural_expected = raw_speech_seconds + sum(pause_values) + 2.0 * edge
    if not fit_to_duration:
        return PacingPlan(
            tempo=1.0,
            pause_seconds=tuple(pause_values),
            edge_silence_seconds=edge,
            target_seconds=target,
            expected_seconds=natural_expected,
            feasible=True,
        )

    if natural_expected > target + 2.0:
        return PacingPlan(
            tempo=1.0,
            pause_seconds=tuple(pause_values),
            edge_silence_seconds=edge,
            target_seconds=target,
            expected_seconds=natural_expected,
            feasible=False,
            warning=(
                "Текст длиннее выбранной длительности. Голос не ускорялся и не искажался; "
                "запись сохранена в естественном темпе."
            ),
        )

    pause_budget = max(0.0, target - raw_speech_seconds - 2.0 * edge)
    scaled_pauses, unplaced = _scale_pauses_to_budget(
        pause_values,
        kinds,
        pause_budget,
        pacing_profile,
    )
    expected = raw_speech_seconds + sum(scaled_pauses) + 2.0 * edge

    warning = None
    feasible = True
    if unplaced > 1.0:
        feasible = False
        warning = (
            "Текста недостаточно для выбранной длительности даже со студийными паузами. "
            "Программа не растягивала голос и не добавляла длинную хвостовую тишину."
        )

    return PacingPlan(
        tempo=1.0,
        pause_seconds=tuple(scaled_pauses),
        edge_silence_seconds=edge,
        target_seconds=target,
        expected_seconds=expected,
        feasible=feasible,
        warning=warning,
    )
