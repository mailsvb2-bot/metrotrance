from __future__ import annotations

from metrotrance.config import Settings
from metrotrance.providers.chatterbox_tts import ChatterboxTTSProvider
from metrotrance.providers.qwen_tts import QwenTTSProvider


class TTSProviderError(RuntimeError):
    pass


def provider_candidates(settings: Settings, requested: str | None = None):
    choice = (requested or settings.tts_provider).lower()
    qwen = QwenTTSProvider(settings)
    chatterbox = ChatterboxTTSProvider(settings)
    if choice == "qwen":
        return [qwen]
    if choice == "chatterbox":
        return [chatterbox]
    if choice == "auto":
        return [qwen, chatterbox]
    if choice == "auto_expressive":
        # Qwen is the safer default for identity stability. Chatterbox remains
        # an experimental fallback until the user approves it in Voice Lab.
        return [qwen, chatterbox]
    raise TTSProviderError(f"Неизвестный TTS_PROVIDER: {choice}")
