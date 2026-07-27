from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
import shutil
import wave
from array import array
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from metrotrance import __version__


VOICE_TEST_CHUNKS = (
    "Добрый вечер. Сейчас можно на мгновение остановиться и спокойно услышать этот голос.",
    "Внутреннее напряжение постепенно растворяется, дыхание остаётся свободным, а речь — ясной и естественной.",
    "За окном меняется свет, знакомая дорога раскрывается глубже, и каждое слово мягко продолжает предыдущее.",
    "А теперь внимание возвращается, голос становится чуть яснее, и вы отчётливо ощущаете настоящий момент.",
)
VOICE_TEST_TEXT = "\n\n".join(VOICE_TEST_CHUNKS)
VOICE_RATING_FIELDS = ("identity", "naturalness", "articulation", "continuity")
VOICE_RATING_LABELS = {
    "identity": "похожесть на ваш голос",
    "naturalness": "живость",
    "articulation": "естественность артикуляции",
    "continuity": "целостность между фразами",
}


@dataclass(frozen=True)
class CandidateSpec:
    id: str
    blind_label: str
    title: str
    provider: str
    profile: str
    expressiveness: int
    seed: int
    description: str

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateMetrics:
    duration_seconds: float
    speech_seconds: float
    sample_rate: int
    channels: int
    peak_dbfs: float
    rms_dbfs: float
    clipped_sample_ratio: float
    silence_fraction: float
    dynamic_range_db: float
    abrupt_jump_ratio: float
    dc_offset: float
    expected_word_count: int
    overall_words_per_minute: float
    speech_words_per_minute: float
    chunk_durations_seconds: tuple[float, ...]
    structural_ok: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("failures", "warnings", "limitations", "chunk_durations_seconds"):
            result[key] = list(result[key])
        return result


def candidate_specs() -> tuple[CandidateSpec, ...]:
    # Labels are intentionally neutral. The UI does not reveal the engine before
    # the listener has made a decision, reducing brand and expectation bias.
    return (
        CandidateSpec(
            id="qwen_identity",
            blind_label="Вариант A",
            title="Qwen — стабильный тембр",
            provider="qwen",
            profile="neutral",
            expressiveness=30,
            seed=11031,
            description="Сдержанная вариативность; приоритет стабильности личности.",
        ),
        CandidateSpec(
            id="qwen_balanced",
            blind_label="Вариант B",
            title="Qwen — естественный баланс",
            provider="qwen",
            profile="warm_natural",
            expressiveness=55,
            seed=22061,
            description="Больше динамики при сохранении чистого голосового референса.",
        ),
        CandidateSpec(
            id="chatterbox_clean",
            blind_label="Вариант C",
            title="Chatterbox — чистый референс",
            provider="chatterbox",
            profile="warm_natural",
            expressiveness=46,
            seed=33091,
            description="Независимый движок; музыкальные студийные записи не используются как prompt.",
        ),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_file_hash(path: Path) -> str | None:
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError:
        return None


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def synthesis_environment_payload(settings) -> dict[str, Any]:
    transcript = ""
    try:
        transcript = settings.voice_transcript.read_text(encoding="utf-8")
    except OSError:
        pass
    return {
        "schema": "metrovoice.environment.v2",
        "product_version": __version__,
        "voice_sha256": _optional_file_hash(settings.voice_audio),
        "transcript_sha256": sha256_text(transcript),
        "voice_metadata_sha256": _optional_file_hash(settings.voice_metadata),
        "pronunciation_dictionary_sha256": _optional_file_hash(settings.pronunciation_dictionary),
        "qwen_model": settings.qwen_tts_model,
        "qwen_device": settings.qwen_tts_device,
        "chatterbox_device": settings.chatterbox_device,
        "packages": {
            "qwen-tts": _package_version("qwen-tts"),
            "chatterbox-tts": _package_version("chatterbox-tts"),
            "torch": _package_version("torch"),
        },
        "candidate_specs": [item.public_dict() for item in candidate_specs()],
        "test_text_sha256": sha256_text(VOICE_TEST_TEXT),
    }


def synthesis_environment_fingerprint(settings) -> str:
    encoded = json.dumps(
        synthesis_environment_payload(settings),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(encoded)


def _dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(min(value, 1.0))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        return wav.getnframes() / rate if rate else 0.0


def _word_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", text))


def analyze_pcm16_voice(
    path: Path,
    *,
    expected_text: str = "",
    speech_parts: Iterable[Path] | None = None,
) -> CandidateMetrics:
    """Measure properties that can be verified from PCM samples.

    No score produced here is called "human" or "natural". Speaker identity,
    articulation and naturalness remain a listening decision. Timing metrics are
    useful only as fail-fast guards against obviously rushed or broken renders.
    """
    if not path.is_file():
        raise FileNotFoundError(path)

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    if sample_width != 2:
        raise ValueError("Voice quality analysis expects PCM16 WAV")
    if sample_rate <= 0 or frame_count <= 0:
        raise ValueError("Empty or invalid WAV")

    samples = array("h")
    samples.frombytes(raw)
    if os_byteorder_is_big_endian():
        samples.byteswap()

    absolute = [abs(value) for value in samples]
    peak = max(absolute, default=0) / 32768.0
    rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples))) / 32768.0
    clipped = sum(1 for value in absolute if value >= 32760) / max(1, len(absolute))
    dc_offset = abs(sum(samples) / max(1, len(samples))) / 32768.0

    mono: list[float] = []
    if channels == 1:
        mono = [float(value) for value in samples]
    else:
        for index in range(0, len(samples), channels):
            frame = samples[index : index + channels]
            if frame:
                mono.append(sum(frame) / len(frame))

    frame_size = max(1, int(sample_rate * 0.020))
    frame_rms: list[float] = []
    silent_frames = 0
    for start in range(0, len(mono), frame_size):
        frame = mono[start : start + frame_size]
        if not frame:
            continue
        level = math.sqrt(sum(value * value for value in frame) / len(frame)) / 32768.0
        frame_rms.append(level)
        if _dbfs(level) < -45.0:
            silent_frames += 1

    nonzero_levels = [level for level in frame_rms if level > 1e-8]
    low = _percentile(nonzero_levels, 0.10)
    high = _percentile(nonzero_levels, 0.90)
    dynamic_range = max(0.0, _dbfs(high) - _dbfs(low)) if low > 0 and high > 0 else 0.0
    silence_fraction = silent_frames / max(1, len(frame_rms))

    jumps = 0
    for left, right in zip(mono, mono[1:]):
        if abs(right - left) >= 20000:
            jumps += 1
    abrupt_jump_ratio = jumps / max(1, len(mono) - 1)

    duration = frame_count / sample_rate
    chunk_durations: tuple[float, ...] = ()
    if speech_parts is not None:
        chunk_durations = tuple(round(_wav_duration(Path(item)), 3) for item in speech_parts)
    speech_seconds = sum(chunk_durations) if chunk_durations else max(0.0, duration * (1.0 - silence_fraction))
    expected_words = _word_count(expected_text)
    overall_wpm = (expected_words * 60.0 / duration) if expected_words and duration else 0.0
    speech_wpm = (expected_words * 60.0 / speech_seconds) if expected_words and speech_seconds else 0.0

    failures: list[str] = []
    warnings: list[str] = []
    if duration < 15.0:
        failures.append("Кандидат короче пятнадцати секунд")
    if peak >= 0.999:
        failures.append("Обнаружено цифровое ограничение по пикам")
    if clipped > 0.0002:
        failures.append("Слишком много клиппующих отсчётов")
    if silence_fraction > 0.70:
        failures.append("Большая часть файла является полной тишиной")
    if abrupt_jump_ratio > 0.0005:
        failures.append("Слишком много резких разрывов формы сигнала")
    if rms < 10 ** (-50.0 / 20.0):
        failures.append("Сигнал практически неслышим")
    if dc_offset > 0.03:
        failures.append("Слишком большое постоянное смещение сигнала")
    elif dc_offset > 0.01:
        warnings.append("Повышенное постоянное смещение сигнала")
    if expected_words:
        if overall_wpm > 105.0 or speech_wpm > 135.0:
            failures.append("Тестовая речь явно слишком быстрая")
        elif overall_wpm > 75.0 or speech_wpm > 95.0:
            warnings.append("Темп выше спокойного трансового диапазона")
        if overall_wpm < 25.0:
            warnings.append("Темп необычно медленный; проверьте растяжения и зависания")
    if dynamic_range < 2.5:
        warnings.append("Очень малая микродинамика; голос может звучать чрезмерно ровно")

    limitations = (
        "Технический анализ не доказывает живость голоса.",
        "Узнаваемость и артикуляция оцениваются человеком по слепому сравнению.",
        "Расчёт темпа основан на ожидаемом тексте и не заменяет распознавание фактически произнесённых слов.",
    )

    return CandidateMetrics(
        duration_seconds=round(duration, 3),
        speech_seconds=round(speech_seconds, 3),
        sample_rate=sample_rate,
        channels=channels,
        peak_dbfs=round(_dbfs(peak), 3),
        rms_dbfs=round(_dbfs(rms), 3),
        clipped_sample_ratio=round(clipped, 8),
        silence_fraction=round(silence_fraction, 5),
        dynamic_range_db=round(dynamic_range, 3),
        abrupt_jump_ratio=round(abrupt_jump_ratio, 8),
        dc_offset=round(dc_offset, 8),
        expected_word_count=expected_words,
        overall_words_per_minute=round(overall_wpm, 2),
        speech_words_per_minute=round(speech_wpm, 2),
        chunk_durations_seconds=chunk_durations,
        structural_ok=not failures,
        failures=tuple(failures),
        warnings=tuple(warnings),
        limitations=limitations,
    )


def os_byteorder_is_big_endian() -> bool:
    import sys

    return sys.byteorder == "big"


def _approval_snapshot_path(settings) -> Path:
    return settings.voice_dir / "approved_candidate.wav"


def load_voice_approval(settings) -> dict[str, Any] | None:
    path = settings.voice_quality_approval
    snapshot = _approval_snapshot_path(settings)
    if not path.is_file() or not settings.voice_audio.is_file() or not snapshot.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema") != "metrovoice.approval.v2":
        return None
    try:
        current_environment = synthesis_environment_fingerprint(settings)
        snapshot_hash = sha256_file(snapshot)
    except OSError:
        return None
    if payload.get("environment_fingerprint") != current_environment:
        return None
    if payload.get("approved_candidate_sha256") != snapshot_hash:
        return None
    ratings = payload.get("ratings") or {}
    if any(int(ratings.get(name, 0)) < 4 for name in VOICE_RATING_FIELDS):
        return None
    return payload


def voice_approval_status(settings) -> dict[str, Any]:
    approval = load_voice_approval(settings)
    if approval is None:
        return {
            "approved": False,
            "detail": (
                "Обычная генерация заблокирована: нужен новый слепой тест голоса "
                "и оценки не ниже 4/5 по всем четырём критериям."
            ),
        }
    return {
        "approved": True,
        "detail": f"Одобрен {approval.get('blind_label', 'вариант')} после слепого прослушивания",
        "approval": {
            key: approval.get(key)
            for key in (
                "job_id",
                "candidate_id",
                "blind_label",
                "candidate_title",
                "provider",
                "profile",
                "expressiveness",
                "seed",
                "ratings",
                "approved_at",
                "notes",
            )
        },
    }


def _validate_ratings(ratings: dict[str, Any]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for name in VOICE_RATING_FIELDS:
        try:
            value = int(ratings.get(name, 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Некорректная оценка: {VOICE_RATING_LABELS[name]}") from exc
        if not 1 <= value <= 5:
            raise ValueError(f"Оцените {VOICE_RATING_LABELS[name]} по шкале 1–5")
        if value < 4:
            raise ValueError(
                f"Нельзя допустить вариант с оценкой ниже 4/5: {VOICE_RATING_LABELS[name]}. "
                "Нажмите «Ни один не годится» и сохраните результат как неудачный."
            )
        normalized[name] = value
    return normalized


def save_voice_approval(
    settings,
    *,
    job_id: str,
    candidate: dict[str, Any],
    ratings: dict[str, Any],
    listened_candidate_ids: Iterable[str],
    required_candidate_ids: Iterable[str],
    notes: str = "",
) -> dict[str, Any]:
    if not settings.voice_audio.is_file():
        raise ValueError("Не найден текущий образец голоса")
    if not candidate.get("metrics", {}).get("structural_ok"):
        raise ValueError("Технически повреждённый кандидат нельзя одобрить")

    listened = {str(item) for item in listened_candidate_ids}
    required = {str(item) for item in required_candidate_ids}
    missing = sorted(required - listened)
    if missing:
        raise ValueError("Сначала прослушайте все готовые варианты до конца или как минимум на две трети")

    normalized_ratings = _validate_ratings(ratings)
    current_environment = synthesis_environment_fingerprint(settings)
    if candidate.get("environment_fingerprint") != current_environment:
        raise ValueError("Параметры голосового движка изменились; создайте новый тест")

    relative = (candidate.get("files") or {}).get("raw") or (candidate.get("files") or {}).get("wav")
    if not relative:
        raise ValueError("Не найден исходный WAV одобренного кандидата")
    candidate_path = (settings.jobs_dir / job_id / str(relative)).resolve()
    try:
        candidate_path.relative_to((settings.jobs_dir / job_id).resolve())
    except ValueError as exc:
        raise ValueError("Некорректный путь кандидата") from exc
    if not candidate_path.is_file():
        raise ValueError("Файл кандидата отсутствует")
    actual_hash = sha256_file(candidate_path)
    expected_hash = candidate.get("raw_sha256") or candidate.get("artifact_sha256")
    if expected_hash != actual_hash:
        raise ValueError("Файл кандидата изменён после теста")

    snapshot = _approval_snapshot_path(settings)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temporary_snapshot = snapshot.with_suffix(".tmp.wav")
    shutil.copy2(candidate_path, temporary_snapshot)
    temporary_snapshot.replace(snapshot)
    snapshot_hash = sha256_file(snapshot)

    payload = {
        "schema": "metrovoice.approval.v2",
        "job_id": job_id,
        "candidate_id": candidate["id"],
        "blind_label": candidate.get("blind_label"),
        "candidate_title": candidate["title"],
        "provider": candidate["provider"],
        "profile": candidate["profile"],
        "expressiveness": int(candidate["expressiveness"]),
        "seed": int(candidate.get("seed", 0)),
        "environment_fingerprint": current_environment,
        "approved_candidate_sha256": snapshot_hash,
        "ratings": normalized_ratings,
        "listened_candidate_ids": sorted(listened),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "notes": str(notes).strip()[:500],
        "declaration": (
            "Кандидат выбран человеком после слепого прослушивания всех готовых вариантов. "
            "Оценка не является научной гарантией неотличимости от живой речи."
        ),
    }
    path = settings.voice_quality_approval
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return payload


def save_voice_rejection(
    settings,
    *,
    job_id: str,
    listened_candidate_ids: Iterable[str],
    required_candidate_ids: Iterable[str],
    notes: str = "",
) -> dict[str, Any]:
    listened = {str(item) for item in listened_candidate_ids}
    required = {str(item) for item in required_candidate_ids}
    if required - listened:
        raise ValueError("Сначала прослушайте все готовые варианты")
    settings.voice_quality_approval.unlink(missing_ok=True)
    _approval_snapshot_path(settings).unlink(missing_ok=True)
    payload = {
        "schema": "metrovoice.rejection.v1",
        "job_id": job_id,
        "environment_fingerprint": synthesis_environment_fingerprint(settings),
        "listened_candidate_ids": sorted(listened),
        "notes": str(notes).strip()[:500],
        "rejected_at": datetime.now(timezone.utc).isoformat(),
    }
    path = settings.voice_dir / "voice_lab_feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload
