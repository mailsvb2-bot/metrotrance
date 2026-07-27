from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from metrotrance.services.audio import mix_studio_layers, wav_info


def write_tone(path: Path, seconds: float, frequency: float, channels: int, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        payload = bytearray()
        for index in range(int(seconds * rate)):
            value = int(math.sin(2 * math.pi * frequency * index / rate) * 3500)
            for _ in range(channels):
                payload.extend(struct.pack("<h", value))
        wav.writeframes(payload)


def test_studio_mix_is_stereo_48khz_and_exports_all_formats(tmp_path: Path) -> None:
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    atmosphere = tmp_path / "atmosphere.wav"
    write_tone(voice, 2.0, 180, 1)
    write_tone(music, 1.0, 220, 2)
    write_tone(atmosphere, 1.3, 80, 2)
    output_wav = tmp_path / "trance.wav"
    output_mp3 = tmp_path / "trance.mp3"
    output_opus = tmp_path / "trance.opus"

    mix_studio_layers(
        voice,
        output_wav,
        output_mp3,
        output_opus,
        music_path=music,
        atmosphere_path=atmosphere,
        music_volume=0.15,
        atmosphere_volume=0.08,
    )

    channels, width, rate, _, duration = wav_info(output_wav)
    assert (channels, width, rate) == (2, 2, 48000)
    assert 1.9 <= duration <= 2.1
    assert output_mp3.stat().st_size > 1000
    assert output_opus.stat().st_size > 1000
