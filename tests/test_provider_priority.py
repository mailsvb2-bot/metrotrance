from types import SimpleNamespace

from metrotrance.providers import provider_candidates


def test_auto_expressive_prefers_qwen_then_chatterbox():
    providers = provider_candidates(SimpleNamespace(tts_provider="auto_expressive"), "auto_expressive")
    assert [provider.name for provider in providers] == ["qwen", "chatterbox"]


def test_legacy_auto_keeps_qwen_first():
    providers = provider_candidates(SimpleNamespace(tts_provider="auto"), "auto")
    assert [provider.name for provider in providers] == ["qwen", "chatterbox"]
