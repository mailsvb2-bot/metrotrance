import pytest

from metrotrance.services.voice_profile import VoiceProfileError, normalize_transcript, validate_transcript


def test_transcript_is_required_and_keeps_fillers():
    text = "  Потому что они стали соответствовать.\n Э-э-э, у них возник раппорт.  "
    normalized = normalize_transcript(text)
    assert normalized == "Потому что они стали соответствовать. Э-э-э, у них возник раппорт."
    assert validate_transcript(normalized) == normalized


def test_short_transcript_is_rejected():
    with pytest.raises(VoiceProfileError):
        validate_transcript("Несколько слов")


def test_fast_reference_is_reported_as_quality_warning(tmp_path):
    import math
    import wave
    from metrotrance.services.voice_profile import assess_voice_profile

    path = tmp_path / "reference.wav"
    rate = 24000
    frames = bytearray()
    for index in range(rate * 30):
        value = int(4000 * math.sin(2 * math.pi * 120 * index / rate))
        frames.extend(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))

    transcript = " ".join(["слово"] * 61)
    result = assess_voice_profile(path, transcript)
    assert result["words_per_minute"] == 122.0
    assert result["warnings"]
