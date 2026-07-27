from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from metrotrance.api import create_app
from metrotrance.config import get_settings


def tone_bytes(seconds: float = 5.2, rate: int = 8000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        payload = bytearray()
        for index in range(int(seconds * rate)):
            payload.extend(struct.pack("<h", int(math.sin(2 * math.pi * 180 * index / rate) * 3000)))
        wav.writeframes(payload)
    return output.getvalue()


def test_upload_list_and_delete_audio_asset(tmp_path: Path) -> None:
    client = TestClient(create_app(get_settings(tmp_path)))
    response = client.post(
        "/api/audio-assets/music",
        files={"file": ("owned.wav", tone_bytes(), "audio/wav")},
        data={
            "title": "Собственная дорожка",
            "category": "warm",
            "license_basis": "owned_exclusive",
            "source_note": "создано владельцем",
            "rights_confirmed": "true",
        },
    )
    assert response.status_code == 200, response.text
    asset = response.json()["asset"]
    assert asset["kind"] == "music"
    assert asset["rights_confirmed"] is True

    listed = client.get("/api/audio-assets?kind=music").json()["assets"]
    assert [item["id"] for item in listed] == [asset["id"]]

    deleted = client.delete(f"/api/audio-assets/{asset['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/audio-assets?kind=music").json()["assets"] == []
