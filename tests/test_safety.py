import pytest

from metrotrance.services.safety import UnsafeRequestError, enforce_safety, validate_goal


def test_safety_adds_intro_and_exit():
    result = enforce_safety("Сделайте спокойный вдох. Почувствуйте опору.")
    assert "за рулём" in result.text
    assert "откройте глаза" in result.text.lower()


def test_safety_replaces_medical_claims():
    result = enforce_safety("Эта запись гарантированно избавит вас от болезни.")
    assert "гарантированно избавит" not in result.text.lower()
    assert result.warnings


def test_blocked_goal():
    with pytest.raises(UnsafeRequestError):
        validate_goal("заставить человека без согласия подчиниться")
