from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from metrotrance.audio_engine.safety_validator import validate_rendered_audio
from metrotrance.services.audio import mix_scene_timeline, wav_info


def tone(path: Path, seconds: float, frequency: float, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        payload = bytearray()
        for i in range(int(seconds * rate)):
            payload.extend(struct.pack("<h", int(math.sin(2 * math.pi * frequency * i / rate) * 2200)))
        wav.writeframes(payload)


def test_scene_renderer_creates_three_formats_and_safety_report(tmp_path: Path) -> None:
    voice = tmp_path / "voice.wav"; ambience = tmp_path / "rain.wav"; event = tmp_path / "horn.wav"
    tone(voice, 4.0, 180); tone(ambience, 2.0, 90); tone(event, 0.7, 320)
    wav_out, mp3_out, opus_out = mix_scene_timeline(
        voice, tmp_path / "out.wav", tmp_path / "out.mp3", tmp_path / "out.opus",
        music_path=None, music_volume=0.1,
        events=[
            {"type":"ambience","start_seconds":0.0,"end_seconds":4.0,"volume_db":-34,
             "fade_in_seconds":0.3,"fade_out_seconds":0.5,"asset_path":str(ambience),"asset_duration_seconds":2.0},
            {"type":"one_shot","start_seconds":1.2,"end_seconds":None,"volume_db":-41,
             "fade_in_seconds":0.1,"fade_out_seconds":0.2,"asset_path":str(event),"asset_duration_seconds":0.7},
        ],
    )
    assert wav_out.exists() and mp3_out.exists() and opus_out.exists()
    assert 3.8 <= wav_info(wav_out)[4] <= 4.1
    report = validate_rendered_audio(wav_out, expected_seconds=4.0)
    assert report.ok
    assert report.duration_seconds > 3.8
