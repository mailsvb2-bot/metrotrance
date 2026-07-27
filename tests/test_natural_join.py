import math
import struct
import wave

from metrotrance.services.audio import concat_wavs, wav_info


def _make_wav(path, seconds=0.08, rate=8000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = [struct.pack("<h", int(math.sin(i / 9.0) * 1200)) for i in range(int(seconds * rate))]
        wav.writeframes(b"".join(frames))


def test_join_uses_low_room_tone_instead_of_absolute_zero(tmp_path):
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    output = tmp_path / "joined.wav"
    _make_wav(first)
    _make_wav(second)

    concat_wavs([first, second], output, pause_seconds=0.2)

    with wave.open(str(output), "rb") as wav:
        rate = wav.getframerate()
        wav.setpos(int(0.08 * rate) + 20)
        gap = wav.readframes(int(0.16 * rate))
    values = struct.unpack("<" + "h" * (len(gap) // 2), gap)
    assert any(value != 0 for value in values)
    assert max(abs(value) for value in values) < 64


def test_natural_join_keeps_requested_duration(tmp_path):
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    _make_wav(first, seconds=0.1)
    _make_wav(second, seconds=0.1)
    output = concat_wavs([first, second], tmp_path / "out.wav", pause_seconds=0.25)
    *_, duration = wav_info(output)
    assert 0.44 < duration < 0.46
