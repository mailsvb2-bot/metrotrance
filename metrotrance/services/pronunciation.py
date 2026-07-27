from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import threading
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from metrotrance.config import Settings

_ACUTE = "\u0301"
_RUSSIAN_WORD = re.compile(r"[А-Яа-яЁё\u0301]+(?:-[А-Яа-яЁё\u0301]+)*")
_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_PLUS_STRESS = re.compile(r"\+([АЕЁИОУЫЭЮЯаеёиоуыэюя])")
_ACCENTOR_SIZE = 53_792_977
_ACCENTOR_SHA256 = "85e5195d7b7b127e94f46704b7c453db651c58de5417f85c31cc021ab6b200b0"


@dataclass(frozen=True)
class PronunciationResult:
    original_text: str
    tts_text: str
    engine: str
    accents_added: int
    yo_added: int
    dictionary_hits: int
    warning: str | None = None

    def report(self) -> dict:
        return asdict(self)


def strip_stress(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("+", "").replace(_ACUTE, ""))


def plus_to_unicode(value: str) -> str:
    """Convert Silero/RUAccent +vowel notation to standard U+0301 notation."""

    def replace(match: re.Match[str]) -> str:
        vowel = match.group(1)
        if vowel in "ёЁ":
            return vowel
        return vowel + _ACUTE

    return unicodedata.normalize("NFC", _PLUS_STRESS.sub(replace, value))


def unicode_to_plus(value: str) -> str:
    output: list[str] = []
    for char in unicodedata.normalize("NFD", value):
        if char == _ACUTE and output:
            previous = output.pop()
            output.extend(["+", previous])
        else:
            output.append(char)
    return unicodedata.normalize("NFC", "".join(output))


def _vowel_count(word: str) -> int:
    return sum(1 for char in word if char in _VOWELS)


def _remove_redundant_monosyllabic_accents(text: str) -> str:
    def clean(match: re.Match[str]) -> str:
        word = match.group(0)
        return word.replace(_ACUTE, "") if _vowel_count(word) <= 1 else word

    return _RUSSIAN_WORD.sub(clean, text)


def _preserve_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def validate_dictionary(entries: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in entries.items():
        key = strip_stress(str(raw_key)).strip().lower()
        value = plus_to_unicode(str(raw_value).strip())
        if not key or not value:
            continue
        if not re.fullmatch(r"[а-яё-]+", key):
            raise ValueError(f"Недопустимое слово в словаре: {raw_key}")
        plain_value = strip_stress(value).lower()
        if plain_value != key:
            raise ValueError(f"Форма справа должна совпадать со словом слева: {raw_key} = {raw_value}")
        if _vowel_count(value) > 1 and _ACUTE not in unicodedata.normalize("NFD", value) and "ё" not in value.lower():
            raise ValueError(f"Не указано ударение: {raw_value}")
        normalized[key] = unicodedata.normalize("NFC", value)
    return normalized


class RussianPronunciation:
    """Contextual Russian stress and pronunciation preprocessor for TTS.

    The original script is never modified. This service builds a separate TTS
    representation with stress marks and ё restoration, then applies a persistent
    user dictionary as the highest-priority override.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._accentor = None
        self._accentor_failed: str | None = None
        self._cache: dict[tuple[str, int], PronunciationResult] = {}
        self._builtins = self._load_builtin_dictionary()

    @property
    def dictionary_path(self) -> Path:
        return self.settings.pronunciation_dictionary

    def _load_builtin_dictionary(self) -> dict[str, str]:
        path = Path(__file__).resolve().parent.parent / "profiles" / "russian_pronunciation.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload.get("dictionary", payload)
            return validate_dictionary({str(k): str(v) for k, v in values.items()})
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return {}

    def load_user_dictionary(self) -> dict[str, str]:
        path = self.dictionary_path
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload.get("dictionary", payload)
            if not isinstance(values, dict):
                return {}
            return validate_dictionary({str(k): str(v) for k, v in values.items()})
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return {}

    def save_user_dictionary(self, entries: dict[str, str]) -> dict[str, str]:
        normalized = validate_dictionary(entries)
        self.dictionary_path.parent.mkdir(parents=True, exist_ok=True)
        self.dictionary_path.write_text(
            json.dumps({"dictionary": normalized}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with self._lock:
            self._cache.clear()
        return normalized

    def dictionary_version(self) -> int:
        path = self.dictionary_path
        return path.stat().st_mtime_ns if path.exists() else 0

    @property
    def bundled_accentor_path(self) -> Path:
        return (
            Path(__file__).resolve().parent.parent
            / "resources"
            / "silero_stress"
            / "accentor.pt"
        )

    @property
    def runtime_accentor_path(self) -> Path:
        """Return a PyTorch-safe model path.

        PyTorch's Windows C++ package reader can fail with ``errno 2`` for a
        perfectly valid file when any directory in its path contains Cyrillic
        or other non-ASCII characters.  MetroTrance therefore stages the model
        under the public Windows profile, whose canonical path is ASCII-only.
        """
        override = os.environ.get("METROTRANCE_STRESS_MODEL")
        if override:
            return Path(override).expanduser()
        if os.name == "nt":
            public_root = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
            return public_root / "MetroTrance" / "models" / "silero_stress" / "accentor.pt"
        return Path.home() / ".metrotrance" / "models" / "silero_stress" / "accentor.pt"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_model_file(self, path: Path) -> tuple[bool, str]:
        if not path.is_file():
            return False, f"файл отсутствует: {path}"
        try:
            size = path.stat().st_size
        except OSError as exc:
            return False, f"файл недоступен: {path}: {exc}"
        if size != _ACCENTOR_SIZE:
            return False, f"неверный размер модели: {path} ({size} вместо {_ACCENTOR_SIZE})"
        try:
            actual_hash = self._sha256(path)
        except OSError as exc:
            return False, f"не удалось прочитать модель: {path}: {exc}"
        if actual_hash != _ACCENTOR_SHA256:
            return False, f"контрольная сумма модели не совпала: {path}"
        return True, "ok"

    def repair_model_cache(self) -> Path:
        """Copy the verified bundled model to a stable per-user cache.

        PyTorch's Windows package reader may reject a valid model when its path
        contains Cyrillic characters.  Copy the verified source atomically to
        the ASCII-only public runtime path before loading it.
        """
        source = self.bundled_accentor_path
        valid, reason = self._validate_model_file(source)
        if not valid:
            raise FileNotFoundError(f"Встроенная модель ударений повреждена или отсутствует: {reason}")

        destination = self.runtime_accentor_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        dest_valid, _ = self._validate_model_file(destination)
        if not dest_valid:
            temporary = destination.with_suffix(".pt.tmp")
            shutil.copyfile(source, temporary)
            copied_valid, copied_reason = self._validate_model_file(temporary)
            if not copied_valid:
                temporary.unlink(missing_ok=True)
                raise OSError(f"Не удалось восстановить модель ударений: {copied_reason}")
            os.replace(temporary, destination)

        with self._lock:
            # A repair can happen after a previous failed health check while the
            # same service object is still alive.  Drop every negative and
            # processed-text cache so the next request really reloads the model.
            self._accentor = None
            self._accentor_failed = None
            self._cache.clear()
        return destination

    @staticmethod
    def _load_accentor_from_file(model_path: Path):
        import torch

        torch.set_num_threads(1)
        accentor = torch.package.PackageImporter(str(model_path)).load_pickle(
            "accentor_models", "accentor"
        )
        quantized_weight = (
            accentor.homosolver.model.bert.embeddings.word_embeddings.weight.data.clone()
        )
        restored_weights = accentor.homosolver.model.bert.scale * (
            quantized_weight - accentor.homosolver.model.bert.zero_point
        )
        accentor.homosolver.model.bert.embeddings.word_embeddings.weight.data = restored_weights
        return accentor

    def _load_accentor(self):
        """Load Silero Stress through an ASCII-safe Windows path.

        A valid model inside a Cyrillic project/user path is readable by Python
        but may be rejected by ``torch.package.PackageImporter``.  On Windows
        the verified source is copied atomically to ``C:\\Users\\Public``
        before PyTorch sees it.
        """
        with self._lock:
            if self._accentor is not None:
                return self._accentor
            if self._accentor_failed is not None:
                return None

            errors: list[str] = []
            runtime = self.runtime_accentor_path
            runtime_valid, runtime_reason = self._validate_model_file(runtime)
            if not runtime_valid:
                try:
                    runtime = self.repair_model_cache()
                    runtime_valid, runtime_reason = self._validate_model_file(runtime)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"подготовка ASCII-копии модели: {exc}")

            if runtime_valid:
                try:
                    self._accentor = self._load_accentor_from_file(runtime)
                    return self._accentor
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"ASCII-копия модели {runtime}: {exc}")
            else:
                errors.append(f"ASCII-копия модели: {runtime_reason}")

            bundled = self.bundled_accentor_path
            bundled_valid, bundled_reason = self._validate_model_file(bundled)
            if bundled_valid and (os.name != "nt" or str(bundled).isascii()):
                try:
                    self._accentor = self._load_accentor_from_file(bundled)
                    return self._accentor
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"встроенная модель: {exc}")
            elif not bundled_valid:
                errors.append(f"встроенная модель: {bundled_reason}")
            else:
                errors.append("встроенная модель находится в Unicode-пути Windows; требуется ASCII-копия")

            if importlib.util.find_spec("silero_stress") is not None:
                try:
                    from silero_stress import load_accentor

                    self._accentor = load_accentor()
                    return self._accentor
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"пакет Silero Stress: {exc}")

            self._accentor_failed = "Автоударения не загрузились: " + " | ".join(errors)
            return None

    def health(self) -> tuple[bool, str]:
        accentor = self._load_accentor()
        if accentor is None:
            return False, self._accentor_failed or "Автоударения недоступны; работает только словарь произношения"
        return True, "Русские ударения: модель MetroTrance в ASCII-пути + словарь исправлений"

    @staticmethod
    def _protect_manual_accents(text: str) -> tuple[str, dict[str, str]]:
        protected: dict[str, str] = {}
        normalized = plus_to_unicode(text)

        def replace(match: re.Match[str]) -> str:
            word = match.group(0)
            if _ACUTE not in unicodedata.normalize("NFD", word):
                return word
            token = f"MTMANUALACCENT{len(protected)}TOKEN"
            protected[token] = word
            return token

        return _RUSSIAN_WORD.sub(replace, normalized), protected

    @staticmethod
    def _restore_manual_accents(text: str, protected: dict[str, str]) -> str:
        for token, word in protected.items():
            text = text.replace(token, word)
        return text

    @staticmethod
    def _apply_dictionary(text: str, dictionary: dict[str, str]) -> tuple[str, int]:
        hits = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal hits
            source = match.group(0)
            key = strip_stress(source).lower()
            replacement = dictionary.get(key)
            if replacement is None:
                return source
            hits += 1
            return _preserve_case(source, replacement)

        return _RUSSIAN_WORD.sub(replace, text), hits

    @staticmethod
    def _count_accents(text: str) -> int:
        return unicodedata.normalize("NFD", text).count(_ACUTE)

    @staticmethod
    def _count_yo_before_after(before: str, after: str) -> int:
        return max(0, after.lower().count("ё") - before.lower().count("ё"))

    def prepare(self, text: str) -> PronunciationResult:
        original = unicodedata.normalize("NFC", text.strip())
        version = self.dictionary_version()
        cache_key = (original, version)
        with self._lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        protected_text, protected = self._protect_manual_accents(original)
        accentor = self._load_accentor()
        warning: str | None = None
        engine = "dictionary_only"
        processed = protected_text
        if accentor is not None:
            try:
                processed = str(accentor(protected_text))
                processed = plus_to_unicode(processed)
                engine = "silero_stress"
            except Exception as exc:  # noqa: BLE001
                warning = f"Автоматическая расстановка ударений не сработала: {exc}"
                engine = "dictionary_only"
        else:
            warning = self._accentor_failed or "Автоматическая расстановка ударений недоступна"

        processed = self._restore_manual_accents(processed, protected)
        processed = _remove_redundant_monosyllabic_accents(processed)

        dictionary = {**self._builtins, **self.load_user_dictionary()}
        processed, hits = self._apply_dictionary(processed, dictionary)
        processed = unicodedata.normalize("NFC", processed)

        result = PronunciationResult(
            original_text=original,
            tts_text=processed,
            engine=engine,
            accents_added=max(0, self._count_accents(processed) - self._count_accents(original)),
            yo_added=self._count_yo_before_after(original, processed),
            dictionary_hits=hits,
            warning=warning,
        )
        with self._lock:
            self._cache[cache_key] = result
        return result

    def prepare_many(self, chunks: list[str]) -> list[PronunciationResult]:
        return [self.prepare(chunk) for chunk in chunks]
