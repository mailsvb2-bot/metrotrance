from metrotrance.models import TranceRequest
from metrotrance.services.script_writer import _max_tokens, build_user_prompt, target_words_for_duration


def test_one_minute_test_has_short_word_target():
    assert 70 <= target_words_for_duration(1) <= 90


def test_one_minute_prompt_is_explicitly_compact():
    request = TranceRequest(goal="проверить звучание", duration_minutes=1)
    prompt = build_user_prompt(request)
    assert "70–90 слов" in prompt
    assert "короткий тест голоса" in prompt
    assert _max_tokens(request) < 500


def test_normal_duration_keeps_full_target():
    request = TranceRequest(goal="расслабление после работы", duration_minutes=10)
    assert target_words_for_duration(10) == 500
    assert _max_tokens(request) >= 1200
    assert "интеграционную" in build_user_prompt(request)
