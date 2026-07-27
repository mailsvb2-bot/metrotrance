from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from metrotrance.config import get_settings
from metrotrance.services.audio_assets import AudioAssetError, AudioAssetLibrary


def write_tone(path: Path, seconds: float = 6.0, rate: int = 12000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for index in range(int(seconds * rate)):
            value = int(math.sin(2 * math.pi * 220 * index / rate) * 4000)
            frames.extend(struct.pack("<h", value))
        wav.writeframes(frames)


def test_audio_library_requires_rights_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "music.wav"
    write_tone(source)
    library = AudioAssetLibrary(get_settings(tmp_path))
    with pytest.raises(AudioAssetError, match="Подтвердите право"):
        library.import_file(
            source,
            original_filename="music.wav",
            kind="music",
            title="Моя музыка",
            category="relaxation",
            license_basis="owned_exclusive",
            source_note="",
            rights_confirmed=False,
        )


def test_audio_library_normalizes_and_persists_license(tmp_path: Path) -> None:
    source = tmp_path / "music.wav"
    write_tone(source)
    library = AudioAssetLibrary(get_settings(tmp_path))
    asset = library.import_file(
        source,
        original_filename="music.wav",
        kind="music",
        title="Тёплая дорожка",
        category="warm",
        license_basis="commissioned_with_rights",
        source_note="Договор 17",
        rights_confirmed=True,
    )
    assert asset.channels == 2
    assert asset.sample_rate == 48000
    assert asset.license_basis == "commissioned_with_rights"
    assert library.path_for(asset).suffix == ".flac"
    assert library.path_for(asset).exists()
    loaded = library.get(asset.id, kind="music")
    assert loaded is not None
    assert loaded.sha256 == asset.sha256
    assert library.delete(asset.id) is True
    assert library.get(asset.id) is None
