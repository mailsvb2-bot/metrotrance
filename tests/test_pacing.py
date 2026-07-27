from metrotrance.services.pacing import build_pacing_plan, preferred_tempo


def test_one_minute_sample_is_never_time_stretched():
    plan = build_pacing_plan(
        raw_speech_seconds=39.6,
        chunk_count=3,
        duration_minutes=1,
        style="мягкий, спокойный",
    )
    assert plan.tempo == 1.0
    assert plan.pause_seconds and min(plan.pause_seconds) >= 0.9
    assert plan.target_seconds == 60.0
    assert plan.warning is not None


def test_style_does_not_reintroduce_post_synthesis_slowdown():
    assert preferred_tempo("нейтральный, ясный", 10) == 1.0
    assert preferred_tempo("глубокий, медленный", 10) == 1.0


def test_studio_profile_uses_pause_budget_without_tail_padding():
    plan = build_pacing_plan(
        raw_speech_seconds=42.0,
        base_pauses=[0.9, 2.3, 3.6, 5.5],
        pause_kinds=["sentence", "ellipsis", "paragraph", "explicit_deep"],
        duration_minutes=1,
        pacing_profile="studio_reference",
    )
    assert plan.tempo == 1.0
    assert plan.expected_seconds <= 60.0
    assert max(plan.pause_seconds) <= 8.0


def test_exact_author_pause_is_preserved():
    plan = build_pacing_plan(
        raw_speech_seconds=20.0,
        base_pauses=[8.0, 0.9],
        pause_kinds=["explicit_exact", "sentence"],
        duration_minutes=1,
    )
    assert plan.pause_seconds[0] == 8.0
