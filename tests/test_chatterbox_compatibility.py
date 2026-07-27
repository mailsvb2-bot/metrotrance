from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from metrotrance.providers.chatterbox_tts import ChatterboxTTSProvider


def _install_fake_module(monkeypatch, cls) -> None:
    package = ModuleType("chatterbox")
    module = ModuleType("chatterbox.mtl_tts")
    module.ChatterboxMultilingualTTS = cls
    package.mtl_tts = module
    monkeypatch.setitem(sys.modules, "chatterbox", package)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", module)


def test_loader_supports_legacy_chatterbox_without_t3_model(monkeypatch) -> None:
    calls: list[dict] = []

    class LegacyModel:
        @classmethod
        def from_pretrained(cls, device):
            calls.append({"device": device})
            return object()

    _install_fake_module(monkeypatch, LegacyModel)
    provider = ChatterboxTTSProvider(SimpleNamespace(chatterbox_device="cpu"))
    model = provider._load()  # noqa: SLF001 - compatibility regression

    assert model is not None
    assert calls == [{"device": "cpu"}]


def test_loader_requests_v3_when_supported(monkeypatch) -> None:
    calls: list[dict] = []

    class V3Model:
        @classmethod
        def from_pretrained(cls, device, t3_model="v2"):
            calls.append({"device": device, "t3_model": t3_model})
            return object()

    _install_fake_module(monkeypatch, V3Model)
    provider = ChatterboxTTSProvider(SimpleNamespace(chatterbox_device="cpu"))
    model = provider._load()  # noqa: SLF001 - compatibility regression

    assert model is not None
    assert calls == [{"device": "cpu", "t3_model": "v3"}]


def test_chatterbox_ignores_studio_reference_paths_and_uses_clean_reference(monkeypatch, tmp_path) -> None:
    generated: list[dict] = []

    class FakeWave:
        pass

    class FakeModel:
        sr = 24000

        def generate(self, text, **kwargs):
            generated.append({"text": text, **kwargs})
            return FakeWave()

    provider = ChatterboxTTSProvider(SimpleNamespace(chatterbox_device="cpu"))
    provider._model = FakeModel()  # noqa: SLF001

    fake_torchaudio = ModuleType("torchaudio")
    fake_torchaudio.save = lambda path, wav, sr: open(path, "wb").write(b"RIFF")
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    clean = tmp_path / "clean.wav"
    clean.write_bytes(b"clean")
    contaminated = tmp_path / "studio-with-music.wav"
    contaminated.write_bytes(b"music")

    provider.synthesize_chunks(
        ["Тестовая фраза."],
        tmp_path / "out",
        clean,
        "Тестовая фраза.",
        performance={"reference_audio_paths": [str(contaminated)]},
    )

    assert generated[0]["audio_prompt_path"] == str(clean)
