from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class NaturalTakeScore:
    score: float
    duration_seconds: float
    seconds_per_character: float
    peak: float
    rms: float
    clipping_ratio: float
    silence_ratio: float
    dynamic_range_db: float
    start_settle_ratio: float
    end_settle_ratio: float

    def public_dict(self) -> dict[str, float]:
        return {key: round(float(value), 6) for key, value in asdict(self).items()}


def _flatten_waveform(waveform: Any) -> list[float]:
    """Convert numpy/torch/list waveforms into one mono float list.

    Providers return slightly different containers.  Keeping this conversion in
    the application lets the natural-take selector stay independent from either
    optional TTS dependency.
    """

    value = waveform
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "reshape"):
        try:
            value = value.reshape(-1)
        except Exception:
            pass
    if hasattr(value, "tolist"):
        value = value.tolist()

    result: list[float] = []

    def append_items(items: Any) -> None:
        if isinstance(items, (list, tuple)):
            for item in items:
                append_items(item)
            return
        try:
            result.append(float(items))
        except (TypeError, ValueError):
            return

    append_items(value)
    return result


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _rms(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(float(item) * float(item) for item in values) / len(values))


def _distance_penalty(value: float, low: float, high: float, weight: float) -> float:
    if low <= value <= high:
        return 0.0
    if value < low:
        distance = (low - value) / max(low, 1e-9)
    else:
        distance = (value - high) / max(high, 1e-9)
    return min(weight, distance * weight)


def score_waveform(waveform: Any, sample_rate: int, expected_text: str) -> NaturalTakeScore:
    """Score a generated take and reject obvious synthetic failure modes.

    This is not marketed as an automatic proof of naturalness.  It is a strict
    technical pre-selector: clipping, implausible speed, dead-flat energy,
    excessive silence and abruptly cut endings lose before the user hears the
    final result.
    """

    samples = _flatten_waveform(waveform)
    if sample_rate <= 0 or not samples:
        return NaturalTakeScore(
            score=-1000.0,
            duration_seconds=0.0,
            seconds_per_character=0.0,
            peak=0.0,
            rms=0.0,
            clipping_ratio=1.0,
            silence_ratio=1.0,
            dynamic_range_db=0.0,
            start_settle_ratio=0.0,
            end_settle_ratio=0.0,
        )

    finite = [max(-1.5, min(1.5, item)) for item in samples if math.isfinite(item)]
    if not finite:
        finite = [0.0]
    duration = len(finite) / float(sample_rate)
    visible_chars = max(1, sum(1 for char in expected_text if not char.isspace()))
    seconds_per_character = duration / visible_chars
    peak = max(abs(item) for item in finite)
    rms = _rms(finite)
    clipping_ratio = sum(1 for item in finite if abs(item) >= 0.995) / len(finite)
    silence_ratio = sum(1 for item in finite if abs(item) <= 0.006) / len(finite)

    window_size = max(1, int(sample_rate * 0.05))
    window_rms = [
        _rms(finite[start : start + window_size])
        for start in range(0, len(finite), window_size)
        if finite[start : start + window_size]
    ]
    active_rms = [item for item in window_rms if item > 0.001]
    if active_rms:
        low = max(_percentile(active_rms, 0.15), 1e-7)
        high = max(_percentile(active_rms, 0.85), low)
        dynamic_range_db = 20.0 * math.log10(high / low)
    else:
        dynamic_range_db = 0.0

    edge_frames = max(1, min(len(finite), int(sample_rate * 0.06)))
    start_rms = _rms(finite[:edge_frames])
    end_rms = _rms(finite[-edge_frames:])
    baseline = max(rms, 1e-7)
    start_settle_ratio = start_rms / baseline
    end_settle_ratio = end_rms / baseline

    score = 100.0
    score -= min(60.0, clipping_ratio * 6000.0)
    score -= _distance_penalty(peak, 0.06, 0.995, 18.0)
    score -= _distance_penalty(rms, 0.012, 0.35, 18.0)
    score -= _distance_penalty(seconds_per_character, 0.035, 0.19, 24.0)
    score -= _distance_penalty(silence_ratio, 0.02, 0.48, 16.0)
    score -= _distance_penalty(dynamic_range_db, 2.2, 20.0, 18.0)

    # A phrase should normally settle at the end instead of being cut while its
    # energy is still above the body average.  Do not force artificial silence:
    # only clearly abrupt endings are penalised.
    if end_settle_ratio > 1.35:
        score -= min(20.0, (end_settle_ratio - 1.35) * 10.0)
    if start_settle_ratio > 1.8:
        score -= min(10.0, (start_settle_ratio - 1.8) * 5.0)

    return NaturalTakeScore(
        score=score,
        duration_seconds=duration,
        seconds_per_character=seconds_per_character,
        peak=peak,
        rms=rms,
        clipping_ratio=clipping_ratio,
        silence_ratio=silence_ratio,
        dynamic_range_db=dynamic_range_db,
        start_settle_ratio=start_settle_ratio,
        end_settle_ratio=end_settle_ratio,
    )


def choose_best_take(
    takes: Iterable[tuple[Any, int]],
    expected_text: str,
) -> tuple[int, Any, int, list[NaturalTakeScore]]:
    """Return ``(index, waveform, sample_rate, scores)`` for the best take."""

    values = list(takes)
    if not values:
        raise ValueError("Нет дублей для выбора")
    scores = [score_waveform(waveform, rate, expected_text) for waveform, rate in values]
    best_index = max(range(len(values)), key=lambda index: scores[index].score)
    waveform, rate = values[best_index]
    return best_index, waveform, rate, scores


def natural_take_count(performance: dict | None = None) -> int:
    performance = performance or {}
    raw = performance.get("takes_per_chunk")
    if raw is None:
        raw = os.getenv("METROTRANCE_NATURAL_TAKES", "2")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 4))


def natural_take_seed(seed_base: int, chunk_index: int, take_index: int) -> int:
    """Create stable but sufficiently separated seeds for adjacent takes."""

    return int((int(seed_base) + chunk_index * 1009 + take_index * 7919) % (2**31 - 1))
