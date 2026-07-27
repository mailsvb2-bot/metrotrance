import pytest
from pydantic import ValidationError

from metrotrance.models import TranceRequest


def test_request_normalizes_spaces():
    request = TranceRequest(goal="  спокойствие   после работы  ")
    assert request.goal == "спокойствие после работы"


def test_request_rejects_too_long_duration():
    with pytest.raises(ValidationError):
        TranceRequest(goal="спокойствие", duration_minutes=60)


def test_request_accepts_one_minute_voice_test():
    request = TranceRequest(goal="проверить голос", duration_minutes=1)
    assert request.duration_minutes == 1


def test_request_rejects_zero_duration():
    with pytest.raises(ValidationError):
        TranceRequest(goal="проверить голос", duration_minutes=0)


def test_request_accepts_ready_text_without_goal():
    request = TranceRequest(content_mode="provided_text", source_text="Это готовый текст для спокойной озвучки без участия сценариста.")
    assert request.goal == ""
    assert request.content_mode == "provided_text"


def test_request_rejects_empty_ready_text():
    with pytest.raises(ValidationError):
        TranceRequest(content_mode="provided_text", source_text="слишком мало")


def test_request_accepts_studio_background_and_profile():
    request = TranceRequest(
        goal="спокойное утро",
        music_style="studio_morning",
        nature_sound="morning_city",
        pacing_profile="studio_reference",
    )
    assert request.music_style == "studio_morning"
    assert request.nature_sound == "morning_city"


def test_job_record_supports_optional_opus_path():
    from metrotrance.models import JobRecord, JobStatus

    record = JobRecord.new("abc123", TranceRequest(goal="проверить экспорт"))
    assert record.status == JobStatus.queued
    assert record.opus_path is None


def test_request_requires_library_asset_id():
    with pytest.raises(ValidationError):
        TranceRequest(goal="спокойствие", music_mode="library")


def test_request_accepts_rights_aware_audio_layers():
    request = TranceRequest(
        goal="спокойствие",
        music_mode="library",
        music_asset_id="music123",
        atmosphere_mode="library",
        atmosphere_asset_id="atmo123",
        performance_profile="studio_melodic",
        tts_provider="auto_expressive",
    )
    assert request.music_asset_id == "music123"
    assert request.atmosphere_asset_id == "atmo123"
    assert request.performance_profile == "studio_melodic"


def test_legacy_background_is_migrated_to_technical_draft():
    request = TranceRequest(goal="спокойствие", music_style="warm_ambient")
    assert request.music_mode == "technical_draft"
