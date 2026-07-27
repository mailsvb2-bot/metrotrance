from pathlib import Path

import pytest

from metrotrance.config import get_settings
from metrotrance.jobs import JobManager
from metrotrance.models import TranceRequest


def test_long_generation_is_fail_closed_until_human_approval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("METROTRANCE_DATA_DIR", str(tmp_path / "data"))
    settings = get_settings(tmp_path)
    manager = JobManager(settings)
    request = TranceRequest(
        workflow_mode="production",
        content_mode="provided_text",
        source_text="Это достаточно длинный тестовый текст для проверки обязательного допуска.",
        duration_minutes=10,
    )

    with pytest.raises(ValueError, match="Обычная генерация заблокирована"):
        manager.create(request)


def test_voice_test_request_does_not_require_goal_or_source_text() -> None:
    request = TranceRequest(workflow_mode="voice_test")
    assert request.workflow_mode == "voice_test"


def test_one_minute_production_is_also_blocked_until_voice_approval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("METROTRANCE_DATA_DIR", str(tmp_path / "data"))
    settings = get_settings(tmp_path)
    manager = JobManager(settings)
    request = TranceRequest(
        workflow_mode="production",
        content_mode="provided_text",
        source_text="Это минутный тест, который больше не должен обходить обязательную проверку живости голоса.",
        duration_minutes=1,
    )

    with pytest.raises(ValueError, match="Обычная генерация заблокирована"):
        manager.create(request)
