from __future__ import annotations

from pathlib import Path

import pytest

from metrotrance.config import get_settings
from metrotrance.services.pronunciation import (
    RussianPronunciation,
    plus_to_unicode,
    strip_stress,
    validate_dictionary,
)


class FakeAccentor:
    def __call__(self, text: str) -> str:
        return text.replace("спокойствие", "спок+ойствие").replace("погружение", "погруж+ение")


def service(tmp_path: Path) -> RussianPronunciation:
    result = RussianPronunciation(get_settings(tmp_path))
    result._accentor = FakeAccentor()  # noqa: SLF001 - deterministic unit fixture
    return result


def test_plus_notation_becomes_unicode_acute() -> None:
    assert plus_to_unicode("молок+о") == "молоко́"
    assert plus_to_unicode("Л+ёва") == "Лёва"


def test_strip_stress_handles_both_notations() -> None:
    assert strip_stress("молоко́") == "молоко"
    assert strip_stress("молок+о") == "молоко"


def test_contextual_result_is_separate_from_original(tmp_path: Path) -> None:
    result = service(tmp_path).prepare("Погружение в спокойствие.")
    assert result.original_text == "Погружение в спокойствие."
    assert result.tts_text == "Погруже́ние в споко́йствие."
    assert result.accents_added == 2


def test_manual_accent_is_preserved(tmp_path: Path) -> None:
    result = service(tmp_path).prepare("Это вручну́ю отмеченное слово.")
    assert "вручну́ю" in result.tts_text


def test_user_dictionary_has_priority(tmp_path: Path) -> None:
    pronunciation = service(tmp_path)
    pronunciation.save_user_dictionary({"спокойствие": "споко́йствие"})
    result = pronunciation.prepare("спокойствие")
    assert result.tts_text == "споко́йствие"
    assert result.dictionary_hits == 1


def test_dictionary_accepts_plus_and_rejects_other_word() -> None:
    assert validate_dictionary({"договор": "догов+ор"}) == {"договор": "догово́р"}
    with pytest.raises(ValueError):
        validate_dictionary({"договор": "звони́т"})


def test_monosyllabic_accents_are_removed(tmp_path: Path) -> None:
    pronunciation = service(tmp_path)
    pronunciation._accentor = lambda text: "+Я н+а д+ом"  # noqa: SLF001
    result = pronunciation.prepare("Я на дом")
    assert result.tts_text == "Я на дом"


def test_source_accentor_is_shipped() -> None:
    pronunciation = RussianPronunciation(get_settings(Path(__file__).resolve().parents[1]))
    assert pronunciation.bundled_accentor_path.exists()
    assert pronunciation.bundled_accentor_path.stat().st_size > 50_000_000


def test_repair_clears_negative_and_text_caches(tmp_path: Path, monkeypatch) -> None:
    pronunciation = service(tmp_path)
    pronunciation._accentor_failed = "old failure"  # noqa: SLF001
    pronunciation._cache[("cached", 0)] = pronunciation.prepare("спокойствие")  # noqa: SLF001
    bundled = tmp_path / "bundled" / "accentor.pt"
    runtime = tmp_path / "runtime" / "accentor.pt"
    bundled.parent.mkdir(parents=True, exist_ok=True)
    bundled.write_bytes(b"model")
    monkeypatch.setattr(
        RussianPronunciation,
        "bundled_accentor_path",
        property(lambda self: bundled),
    )
    monkeypatch.setattr(
        RussianPronunciation,
        "runtime_accentor_path",
        property(lambda self: runtime),
    )
    monkeypatch.setattr(
        pronunciation,
        "_validate_model_file",
        lambda path: (path.exists(), "ok" if path.exists() else "missing"),
    )
    result = pronunciation.repair_model_cache()
    assert result.exists()
    assert pronunciation._accentor is None  # noqa: SLF001
    assert pronunciation._accentor_failed is None  # noqa: SLF001
    assert pronunciation._cache == {}  # noqa: SLF001
