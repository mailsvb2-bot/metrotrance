from metrotrance.services.studio_profile import load_studio_profile, recommended_word_range, target_words


def test_studio_profile_matches_measured_reference():
    profile = load_studio_profile()
    assert profile["source_word_count"] == 1526
    assert 47.0 < profile["overall_words_per_minute"] < 49.0
    assert profile["pause_share"]["min"] >= 0.30


def test_thirty_minute_word_range_is_not_inflated():
    assert recommended_word_range(30) == (1350, 1650)
    assert target_words(30) == 1500
