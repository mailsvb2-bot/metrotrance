from metrotrance.services.local_llama import strip_reasoning
from windows_installer import select_model_tier


def test_auto_model_tier_uses_ram_thresholds() -> None:
    assert select_model_tier("auto", 8) == "fast"
    assert select_model_tier("auto", 16) == "quality"
    assert select_model_tier("auto", 32) == "max"


def test_explicit_model_tier_wins() -> None:
    assert select_model_tier("fast", 64) == "fast"
    assert select_model_tier("max", 8) == "max"


def test_reasoning_is_removed_from_spoken_script() -> None:
    text = "<think>internal plan</think>Готовый текст для озвучки."
    assert strip_reasoning(text) == "Готовый текст для озвучки."
