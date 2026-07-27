import math
import struct
import wave

from metrotrance.services.audio import concat_wavs, wav_info


def make_wav(path, seconds=0.1, rate=8000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = [struct.pack("<h", int(math.sin(i / 10) * 1000)) for i in range(int(seconds * rate))]
        wav.writeframes(b"".join(frames))


def test_concat_adds_pause(tmp_path):
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    make_wav(first)
    make_wav(second)
    output = concat_wavs([first, second], tmp_path / "out.wav", pause_seconds=0.2)
    *_, duration = wav_info(output)
    assert 0.38 < duration < 0.42


def test_concat_can_pad_short_voice_test(tmp_path):
    first = tmp_path / "a.wav"
    make_wav(first, seconds=0.1)
    output = concat_wavs([first], tmp_path / "padded.wav", edge_silence_seconds=0.1, minimum_duration_seconds=0.5)
    *_, duration = wav_info(output)
    assert 0.49 < duration < 0.51


def test_concat_supports_variable_pauses(tmp_path):
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    third = tmp_path / "c.wav"
    make_wav(first)
    make_wav(second)
    make_wav(third)
    output = concat_wavs([first, second, third], tmp_path / "variable.wav", pause_seconds=[0.1, 0.3])
    *_, duration = wav_info(output)
    assert 0.68 < duration < 0.72


def _wav_format_tag(path):
    data = path.read_bytes()
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        if chunk_id == b"fmt ":
            return int.from_bytes(data[offset + 8 : offset + 10], "little")
        offset += 8 + size + (size % 2)
    raise AssertionError("fmt chunk not found")


def test_normalizes_wave_format_extensible_to_pcm16(tmp_path):
    import subprocess

    from metrotrance.services.audio import ffmpeg_executable, normalize_wav_pcm16

    source = tmp_path / "source.wav"
    make_wav(source, seconds=0.2, rate=24000)
    extensible = tmp_path / "extensible.wav"
    result = subprocess.run(
        [
            ffmpeg_executable(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(extensible),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert _wav_format_tag(extensible) == 65534

    normalized = normalize_wav_pcm16(extensible, tmp_path / "normalized.wav")
    assert _wav_format_tag(normalized) == 1
    channels, width, rate, _, duration = wav_info(normalized)
    assert (channels, width, rate) == (1, 2, 24000)
    assert 0.19 < duration < 0.21


def test_voice_only_exports_opus(tmp_path):
    from metrotrance.services.audio import master_voice_only

    source = tmp_path / "voice.wav"
    make_wav(source, seconds=0.25, rate=24000)
    wav_path, mp3_path, opus_path = master_voice_only(
        source,
        tmp_path / "trance.wav",
        tmp_path / "trance.mp3",
        tmp_path / "trance.opus",
    )
    assert wav_path.exists() and wav_path.stat().st_size > 1000
    assert mp3_path.exists() and mp3_path.stat().st_size > 100
    assert opus_path.exists() and opus_path.stat().st_size > 100
    assert opus_path.read_bytes()[:4] == b"OggS"
