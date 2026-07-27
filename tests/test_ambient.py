from metrotrance.services.ambient import generate_ambient_wav
from metrotrance.services.audio import wav_info


def test_ambient_generation(tmp_path):
    path = generate_ambient_wav(tmp_path / "ambient.wav", 0.25, sample_rate=8000)
    channels, width, rate, frames, duration = wav_info(path)
    assert channels == 1
    assert width == 2
    assert rate == 8000
    assert frames > 0
    assert 0.20 < duration < 0.30


def test_background_variants_generate(tmp_path):
    for music in ("none", "warm_ambient", "deep_ambient", "studio_morning"):
        for nature in ("none", "rain", "ocean", "brown_noise", "morning_city", "forest_birds"):
            path = generate_ambient_wav(
                tmp_path / f"{music}-{nature}.wav",
                0.05,
                sample_rate=4000,
                music_style=music,
                nature_sound=nature,
            )
            assert path.exists()
