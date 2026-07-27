import math

from metrotrance.services.natural_voice import (
    choose_best_take,
    natural_take_count,
    natural_take_seed,
    score_waveform,
)


def _sine(seconds: float, rate: int = 24000, amplitude: float = 0.18, modulation: bool = True):
    values = []
    total = int(seconds * rate)
    for index in range(total):
        envelope = 0.72 + 0.28 * math.sin(index / 1700.0) if modulation else 1.0
        values.append(math.sin(index * 2.0 * math.pi * 115.0 / rate) * amplitude * envelope)
    return values


def test_score_rejects_clipped_take():
    clean = score_waveform(_sine(2.4), 24000, "Спокойная естественная фраза")
    clipped = score_waveform([1.0 if index % 2 else -1.0 for index in range(24000 * 2)], 24000, "Фраза")
    assert clean.score > clipped.score
    assert clipped.clipping_ratio > 0.99


def test_score_prefers_energy_shape_over_dead_flat_take():
    expressive = _sine(2.8, modulation=True)
    dead_flat = _sine(2.8, modulation=False)
    expressive_score = score_waveform(expressive, 24000, "Длинная фраза с живым изменением внутренней энергии")
    flat_score = score_waveform(dead_flat, 24000, "Длинная фраза с живым изменением внутренней энергии")
    assert expressive_score.dynamic_range_db > flat_score.dynamic_range_db
    assert expressive_score.score > flat_score.score


def test_choose_best_take_returns_score_table():
    bad = [0.0] * 24000
    good = _sine(2.0)
    index, waveform, rate, scores = choose_best_take([(bad, 24000), (good, 24000)], "Естественная речь")
    assert index == 1
    assert waveform is good
    assert rate == 24000
    assert len(scores) == 2


def test_take_count_is_bounded(monkeypatch):
    monkeypatch.setenv("METROTRANCE_NATURAL_TAKES", "99")
    assert natural_take_count() == 4
    assert natural_take_count({"takes_per_chunk": 1}) == 1


def test_take_seeds_are_stable_and_distinct():
    first = natural_take_seed(100, 1, 0)
    second = natural_take_seed(100, 1, 1)
    assert first == natural_take_seed(100, 1, 0)
    assert first != second
