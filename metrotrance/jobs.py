from __future__ import annotations

import json
import random
import threading
import traceback
import uuid
from dataclasses import replace
from pathlib import Path

from metrotrance import __version__
from metrotrance.audio_engine import SoundEvent, SoundPlan, build_sound_plan
from metrotrance.audio_engine.director import resolve_sound_plan, select_auto_music
from metrotrance.audio_engine.safety_validator import validate_rendered_audio
from metrotrance.config import Settings
from metrotrance.models import JobRecord, JobStatus, TranceRequest
from metrotrance.providers import provider_candidates
from metrotrance.services.ambient import generate_ambient_wav
from metrotrance.services.audio_assets import AudioAssetLibrary, copy_asset_for_job
from metrotrance.services.audio import (
    concat_wavs,
    master_voice_only,
    mix_and_master,
    mix_studio_layers,
    mix_scene_timeline,
    normalize_tts_parts,
    wav_info,
    write_manifest,
)
from metrotrance.services.chunker import segment_text
from metrotrance.services.pacing import build_pacing_plan
from metrotrance.services.performance_director import (
    apply_pause_shape,
    build_performance_plan,
    profile_public_dict,
    prompt_paths,
    provider_payload,
    resolve_style_family,
)
from metrotrance.services.pronunciation import RussianPronunciation
from metrotrance.services.voice_quality import (
    VOICE_TEST_CHUNKS,
    VOICE_TEST_TEXT,
    analyze_pcm16_voice,
    candidate_specs,
    load_voice_approval,
    sha256_file,
    synthesis_environment_fingerprint,
)
from metrotrance.services.safety import enforce_safety, validate_goal
from metrotrance.services.script_writer import create_script_writer


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        self._cancelled: set[str] = set()
        self._load_existing()

    def _job_file(self, job_id: str) -> Path:
        return self.settings.jobs_dir / job_id / "job.json"

    def _load_existing(self) -> None:
        for path in self.settings.jobs_dir.glob("*/job.json"):
            try:
                record = JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
                if record.status in {JobStatus.queued, JobStatus.running}:
                    record.status = JobStatus.failed
                    record.error = "Приложение было остановлено до завершения задания"
                    record.stage = "Прервано"
                self._jobs[record.id] = record
            except Exception:
                continue

    def _save(self, record: JobRecord) -> None:
        record.touch()
        path = self._job_file(record.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def _update(self, job_id: str, **changes) -> JobRecord:
        with self._lock:
            record = self._jobs[job_id]
            for key, value in changes.items():
                setattr(record, key, value)
            self._save(record)
            return record.model_copy(deep=True)

    def create(self, request: TranceRequest) -> JobRecord:
        if request.workflow_mode == "production" and request.content_mode != "provided_text":
            validate_goal(request.goal)
        if (
            request.workflow_mode == "production"
            and load_voice_approval(self.settings) is None
        ):
            raise ValueError(
                "Обычная генерация заблокирована. Сначала создайте 30-секундные "
                "кандидаты голоса, прослушайте их и одобрите один вариант."
            )
        job_id = uuid.uuid4().hex[:12]
        record = JobRecord.new(job_id, request)
        with self._lock:
            self._jobs[job_id] = record
            self._save(record)
        thread = threading.Thread(target=self._run, args=(job_id,), name=f"metrotrance-{job_id}", daemon=True)
        thread.start()
        return record.model_copy(deep=True)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted((j.model_copy(deep=True) for j in self._jobs.values()), key=lambda x: x.created_at, reverse=True)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            return record.model_copy(deep=True) if record else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            self._cancelled.add(job_id)
            return True

    def _check_cancelled(self, job_id: str) -> None:
        if job_id in self._cancelled:
            self._update(job_id, status=JobStatus.cancelled, stage="Отменено", progress=0)
            raise InterruptedError("Задание отменено")


    def _run_voice_test(
        self,
        job_id: str,
        record: JobRecord,
        job_dir: Path,
        reference: Path,
        transcript: str,
    ) -> None:
        """Render several short candidates and require a human decision.

        This is deliberately a calibration workflow, not an automatic claim of
        naturalness. Studio recordings with music are not passed into TTS.
        """
        script_path = job_dir / "script.txt"
        script_path.write_text(VOICE_TEST_TEXT, encoding="utf-8")
        pronunciation = RussianPronunciation(self.settings)
        pronunciation_results = pronunciation.prepare_many(list(VOICE_TEST_CHUNKS))
        tts_chunks = [item.tts_text for item in pronunciation_results]
        tts_script_path = job_dir / "tts_script_with_stress.txt"
        tts_script_path.write_text("\n\n".join(tts_chunks), encoding="utf-8")

        report_path = job_dir / "pronunciation_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "engine": pronunciation_results[0].engine if pronunciation_results else "none",
                    "accents_added": sum(item.accents_added for item in pronunciation_results),
                    "yo_added": sum(item.yo_added for item in pronunciation_results),
                    "dictionary_hits": sum(item.dictionary_hits for item in pronunciation_results),
                    "chunks": [item.report() for item in pronunciation_results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        candidates: list[dict] = []
        errors: list[str] = []
        provider_cache: dict[str, object] = {}
        specs = list(candidate_specs())
        labels = [chr(65 + index) for index in range(len(specs))]
        random.Random(int(job_id[:8], 16) if all(ch in "0123456789abcdef" for ch in job_id[:8].lower()) else job_id).shuffle(labels)
        # Generate equal providers consecutively to avoid keeping Qwen and
        # Chatterbox in memory at the same time. Labels remain randomly assigned
        # and candidates are sorted by label only after generation.
        specs = tuple(replace(spec, blind_label=f"Вариант {label}") for spec, label in zip(specs, labels))
        remaining_by_provider = {provider: sum(1 for item in specs if item.provider == provider) for provider in {item.provider for item in specs}}
        environment_fingerprint = synthesis_environment_fingerprint(self.settings)
        for position, spec in enumerate(specs, start=1):
            self._check_cancelled(job_id)
            self._update(
                job_id,
                progress=15 + position * 20,
                stage=f"Кандидат {position}/{len(specs)}: {spec.title}",
            )
            provider = provider_cache.get(spec.provider)
            if provider is None:
                provider = provider_candidates(self.settings, spec.provider)[0]
                provider_cache[spec.provider] = provider
            ok, detail = provider.health()
            if not ok:
                errors.append(f"{spec.title}: {detail}")
                continue

            candidate_dir = job_dir / "candidates" / spec.id
            raw_dir = candidate_dir / "raw"
            normalized_dir = candidate_dir / "pcm16"
            try:
                parts = provider.synthesize_chunks(
                    tts_chunks,
                    raw_dir,
                    reference,
                    transcript,
                    performance={
                        "profile": spec.profile,
                        "expressiveness": spec.expressiveness,
                        "style": "естественная спокойная речь",
                        "cues": [],
                        "studio_reference_bank": False,
                        "seed": spec.seed,
                    },
                )
                normalized = normalize_tts_parts(parts, normalized_dir)
                voice_wav = concat_wavs(
                    normalized,
                    candidate_dir / "voice.wav",
                    pause_seconds=[1.15, 1.8, 2.2],
                    edge_silence_seconds=0.35,
                )
                final_wav, final_mp3, final_opus = master_voice_only(
                    voice_wav,
                    candidate_dir / "candidate.wav",
                    candidate_dir / "candidate.mp3",
                    candidate_dir / "candidate.opus",
                )
                metrics = analyze_pcm16_voice(
                    final_wav,
                    expected_text=VOICE_TEST_TEXT,
                    speech_parts=normalized,
                )
                candidates.append(
                    {
                        **spec.public_dict(),
                        "status": "ready",
                        "environment_fingerprint": environment_fingerprint,
                        "raw_sha256": sha256_file(voice_wav),
                        "artifact_sha256": sha256_file(final_wav),
                        "metrics": metrics.public_dict(),
                        "files": {
                            "raw": str(voice_wav.relative_to(job_dir)),
                            "wav": str(final_wav.relative_to(job_dir)),
                            "mp3": str(final_mp3.relative_to(job_dir)),
                            "opus": str(final_opus.relative_to(job_dir)),
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{spec.title}: {exc}")
                candidates.append(
                    {
                        **spec.public_dict(),
                        "status": "failed",
                        "error": str(exc),
                        "metrics": {"structural_ok": False},
                        "files": {},
                    }
                )
            finally:
                remaining_by_provider[spec.provider] -= 1
                if remaining_by_provider[spec.provider] == 0:
                    release = getattr(provider, "release", None)
                    if callable(release):
                        release()
                    provider_cache.pop(spec.provider, None)

        candidates.sort(key=lambda item: str(item.get("blind_label", "")))
        ready = [item for item in candidates if item.get("status") == "ready"]
        if not ready:
            raise RuntimeError(
                "Не удалось создать ни одного кандидата голоса. " + " | ".join(errors)
            )

        index_path = job_dir / "voice_candidates.json"
        index_path.write_text(
            json.dumps(
                {
                    "schema": "metrovoice.candidates.v2",
                    "workflow": "voice_test",
                    "human_approval_required": True,
                    "naturalness_automatically_verified": False,
                    "environment_fingerprint": environment_fingerprint,
                    "blind_comparison": True,
                    "candidates": candidates,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        first = ready[0]
        first_files = first["files"]
        metadata = {
            "workflow_mode": "voice_test",
            "human_approval_required": True,
            "naturalness_automatically_verified": False,
            "blind_comparison": True,
            "environment_fingerprint": environment_fingerprint,
            "voice_candidates": [
                {
                    key: candidate.get(key)
                    for key in (
                        "id",
                        "blind_label",
                        "title",
                        "provider",
                        "profile",
                        "expressiveness",
                        "seed",
                        "description",
                        "status",
                        "error",
                        "environment_fingerprint",
                        "raw_sha256",
                        "artifact_sha256",
                        "metrics",
                        "files",
                    )
                }
                for candidate in candidates
            ],
            "candidate_index_path": str(index_path),
        }
        write_manifest(
            job_dir / "manifest.json",
            {"request": record.request.model_dump(), **metadata},
        )
        self._update(
            job_id,
            status=JobStatus.completed,
            progress=100,
            stage="Кандидаты готовы — выберите голос на слух",
            output_dir=str(job_dir),
            script_path=str(script_path),
            tts_script_path=str(tts_script_path),
            pronunciation_report_path=str(report_path),
            wav_path=str(job_dir / first_files["wav"]),
            mp3_path=str(job_dir / first_files["mp3"]),
            opus_path=str(job_dir / first_files["opus"]),
            warnings=list(
                dict.fromkeys(
                    errors
                    + [
                        "Техническая проверка не доказывает живость. "
                        "Создание транса откроется только после вашего прослушивания и выбора."
                    ]
                )
            ),
            metadata=metadata,
        )
    def _run(self, job_id: str) -> None:
        record = self.get(job_id)
        if record is None:
            return
        job_dir = self.settings.jobs_dir / job_id
        chunks_dir = job_dir / "chunks"
        job_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._update(job_id, status=JobStatus.running, progress=5, stage="Проверка конфигурации")
            self._check_cancelled(job_id)
            reference = self.settings.voice_audio
            transcript_path = self.settings.voice_transcript
            if not reference.exists():
                raise RuntimeError("Сначала сохраните образец вашего голоса в настройках")
            transcript = transcript_path.read_text(encoding="utf-8").strip() if transcript_path.exists() else ""
            if not transcript:
                raise RuntimeError(
                    "Сохраните точную расшифровку образца голоса. "
                    "Озвучка только по отпечатку голоса отключена из-за плохого качества."
                )

            if record.request.workflow_mode == "voice_test":
                self._run_voice_test(job_id, record, job_dir, reference, transcript)
                return

            approved_choice = load_voice_approval(self.settings)
            effective_provider = (
                str(approved_choice.get("provider"))
                if approved_choice is not None
                else record.request.tts_provider
            )
            effective_profile = (
                str(approved_choice.get("profile"))
                if approved_choice is not None
                else record.request.performance_profile
            )
            effective_expressiveness = (
                int(approved_choice.get("expressiveness", record.request.expressiveness))
                if approved_choice is not None
                else record.request.expressiveness
            )
            effective_seed = (
                int(approved_choice.get("seed", int(job_id[:8], 16)))
                if approved_choice is not None
                else int(job_id[:8], 16)
            )

            script_warnings: list[str] = []
            if approved_choice is not None:
                script_warnings.append(
                    f"Используется одобренный вами голосовой вариант: "
                    f"{approved_choice.get('candidate_title', approved_choice.get('candidate_id'))}."
                )
            if record.request.content_mode == "provided_text":
                self._update(job_id, progress=18, stage="Подготовка вашего текста — без ИИ")
                script_text = record.request.source_text.strip()
                script_provider = "provided_text"
            else:
                stage = "ИИ быстро пишет сценарий" if record.request.content_mode == "ai_fast" else "ИИ пишет и редактирует сценарий"
                self._update(job_id, progress=12, stage=stage)
                writer = create_script_writer(self.settings)
                try:
                    script_raw = writer.generate(record.request)
                finally:
                    writer.release()
                self._check_cancelled(job_id)

                self._update(job_id, progress=28, stage="Проверка сценария")
                safety = enforce_safety(script_raw, compact=record.request.duration_minutes <= 1)
                script_text = safety.text
                script_warnings.extend(safety.warnings)
                script_provider = self.settings.script_provider

            script_path = job_dir / "script.txt"
            script_path.write_text(script_text, encoding="utf-8")

            if effective_profile == "studio_melodic":
                max_chars = 220 if record.request.duration_minutes <= 1 else 340
                min_chars = 70 if record.request.duration_minutes <= 1 else 110
            else:
                max_chars = 180 if record.request.duration_minutes <= 1 else 260
                min_chars = 50 if record.request.duration_minutes <= 1 else 70
            segments = segment_text(
                script_text,
                max_chars=max_chars,
                min_chars=min_chars,
                profile=record.request.pacing_profile,
            )
            if not segments:
                raise RuntimeError("Не удалось разделить текст на смысловые фрагменты")
            chunks = [segment.text for segment in segments]
            base_pauses = [segment.pause_after for segment in segments[:-1]]
            pause_kinds = [segment.pause_kind for segment in segments[:-1]]

            self._update(job_id, progress=32, stage="Проверка русских ударений и произношения")
            pronunciation = RussianPronunciation(self.settings)
            pronunciation_results = pronunciation.prepare_many(chunks)
            tts_chunks = [item.tts_text for item in pronunciation_results]
            pronunciation_warnings = [item.warning for item in pronunciation_results if item.warning]
            script_warnings.extend(str(item) for item in dict.fromkeys(pronunciation_warnings))
            tts_script_path = job_dir / "tts_script_with_stress.txt"
            tts_script_path.write_text("\n\n".join(tts_chunks), encoding="utf-8")
            pronunciation_report_path = job_dir / "pronunciation_report.json"
            pronunciation_report_path.write_text(
                json.dumps(
                    {
                        "engine": pronunciation_results[0].engine if pronunciation_results else "none",
                        "accents_added": sum(item.accents_added for item in pronunciation_results),
                        "yo_added": sum(item.yo_added for item in pronunciation_results),
                        "dictionary_hits": sum(item.dictionary_hits for item in pronunciation_results),
                        "chunks": [item.report() for item in pronunciation_results],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            style_family_selection = resolve_style_family(
                record.request.studio_style_family,
                goal=record.request.goal,
                style=record.request.style,
                ending_state=record.request.ending_state,
                extra_notes=record.request.extra_notes,
                source_text=script_text,
            )
            performance_plan = build_performance_plan(
                chunks,
                enabled=effective_profile == "studio_melodic",
                user_expressiveness=effective_expressiveness,
                style_family=record.request.studio_style_family,
                goal=record.request.goal,
                style=record.request.style,
                ending_state=record.request.ending_state,
                extra_notes=record.request.extra_notes,
                source_text=script_text,
                selection=style_family_selection,
            )
            base_pauses = apply_pause_shape(base_pauses, performance_plan)
            performance_plan_path = job_dir / "performance_plan.json"
            performance_plan_path.write_text(
                json.dumps(
                    {
                        "profile": profile_public_dict(),
                        "mode": effective_profile,
                        "studio_style_transfer": False,
                        "style_family": style_family_selection.public_dict(),
                        "cues": [cue.public_dict() for cue in performance_plan],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (job_dir / "chunks.json").write_text(
                json.dumps(
                    [
                        {
                            "text": segment.text,
                            "tts_text": pronunciation_results[index].tts_text,
                            "pause_after": base_pauses[index] if index < len(base_pauses) else 0.0,
                            "pause_kind": segment.pause_kind,
                            "performance": performance_plan[index].public_dict() if index < len(performance_plan) else None,
                        }
                        for index, segment in enumerate(segments)
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._check_cancelled(job_id)

            self._update(job_id, progress=36, stage=f"Озвучка: {len(tts_chunks)} смысловых фрагментов")
            tts_errors: list[str] = []
            audio_parts = None
            selected_provider = None
            for provider in provider_candidates(self.settings, effective_provider):
                ok, detail = provider.health()
                if not ok:
                    tts_errors.append(detail)
                    continue
                try:
                    audio_parts = provider.synthesize_chunks(
                        tts_chunks,
                        chunks_dir,
                        reference,
                        transcript,
                        performance={
                            "profile": effective_profile,
                            "expressiveness": effective_expressiveness,
                            "style": record.request.style,
                            "cues": provider_payload(performance_plan),
                            "studio_reference_bank": False,
                            "style_family": style_family_selection.selected,
                            "seed": effective_seed,
                        },
                    )
                    selected_provider = provider.name
                    break
                except Exception as exc:  # noqa: BLE001
                    tts_errors.append(f"{provider.name}: {exc}")
                finally:
                    release = getattr(provider, "release", None)
                    if callable(release):
                        release()
            if not audio_parts:
                raise RuntimeError("Не удалось запустить синтез речи. " + " | ".join(tts_errors))
            self._check_cancelled(job_id)

            self._update(job_id, progress=68, stage="Нормализация WAV-фрагментов")
            audio_parts = normalize_tts_parts(audio_parts, chunks_dir / "pcm16")
            speech_part_durations = [wav_info(path)[4] for path in audio_parts]
            raw_speech_seconds = sum(speech_part_durations)
            pacing = build_pacing_plan(
                raw_speech_seconds,
                base_pauses,
                record.request.duration_minutes,
                record.request.style,
                pause_kinds=pause_kinds,
                fit_to_duration=record.request.duration_mode == "fit",
                pacing_profile=record.request.pacing_profile,
            )
            if pacing.warning:
                script_warnings.append(pacing.warning)

            self._update(job_id, progress=74, stage="Расстановка студийных смысловых пауз")
            voice_wav = concat_wavs(
                audio_parts,
                job_dir / "voice.wav",
                pause_seconds=pacing.pause_seconds,
                edge_silence_seconds=pacing.edge_silence_seconds,
            )
            channels, _, sample_rate, _, duration = wav_info(voice_wav)
            if channels != 1:
                raise RuntimeError("Ожидался монофонический голосовой WAV")

            self._update(job_id, progress=78, stage="Анализ звуковых сцен и построение таймлайна")
            sound_plan = build_sound_plan(
                chunks,
                speech_part_durations,
                list(pacing.pause_seconds),
                pacing.edge_silence_seconds,
                duration,
                mode=record.request.sound_design_mode,
            )

            self._check_cancelled(job_id)
            library = AudioAssetLibrary(self.settings)
            music_path = None
            atmosphere_path = None
            music_passport = None
            atmosphere_passport = None

            if record.request.music_mode == "auto_library":
                preferred_categories = []
                combined_hint = f"{record.request.goal} {record.request.style} {record.request.extra_notes}".lower()
                if any(word in combined_hint for word in ("утро", "проснуться", "бодр")):
                    preferred_categories.append("morning")
                if any(word in combined_hint for word in ("сон", "уснуть", "ноч")):
                    preferred_categories.append("sleep")
                if any(word in combined_hint for word in ("глубок", "транс", "погруж")):
                    preferred_categories.append("deep")
                asset = select_auto_music(library, seed=job_id, preferred_categories=preferred_categories)
                if asset is not None:
                    music_path = copy_asset_for_job(library, asset, job_dir)
                    music_passport = asset.public_dict()
                else:
                    script_warnings.append(
                        "Автоматическая музыка не выбрана: в библиотеке нет вручную проверенной безопасной дорожки."
                    )
            elif record.request.music_mode == "library":
                asset = library.get(record.request.music_asset_id or "", kind="music")
                if asset is None:
                    raise RuntimeError("Выбранная музыкальная дорожка отсутствует в библиотеке")
                music_path = copy_asset_for_job(library, asset, job_dir)
                music_passport = asset.public_dict()
            elif record.request.music_mode == "technical_draft":
                self._update(job_id, progress=82, stage="Создание черновой технической музыкальной подложки")
                technical_style = record.request.music_style if record.request.music_style != "none" else "warm_ambient"
                music_path = generate_ambient_wav(
                    job_dir / "technical_music.wav",
                    duration,
                    sample_rate,
                    seed=int(job_id[:8], 16),
                    music_style=technical_style,
                    nature_sound="none",
                )
                music_passport = {
                    "kind": "music",
                    "origin": "procedural_technical_draft",
                    "title": "Черновая техническая подложка MetroTrance",
                    "copyright_note": "Синусоиды и процедурный шум; не студийная композиция",
                }
                script_warnings.append(
                    "Использована черновая процедурная подложка. Для качественного результата загрузите лицензированную музыку."
                )

            if record.request.atmosphere_mode == "library":
                asset = library.get(record.request.atmosphere_asset_id or "", kind="atmosphere")
                if asset is None:
                    raise RuntimeError("Выбранная атмосферная дорожка отсутствует в библиотеке")
                atmosphere_path = copy_asset_for_job(library, asset, job_dir)
                atmosphere_passport = asset.public_dict()
            elif record.request.atmosphere_mode == "technical_draft":
                self._update(job_id, progress=84, stage="Создание черновой технической атмосферы")
                technical_nature = record.request.nature_sound if record.request.nature_sound != "none" else "brown_noise"
                atmosphere_path = generate_ambient_wav(
                    job_dir / "technical_atmosphere.wav",
                    duration,
                    sample_rate,
                    seed=int(job_id[4:12], 16),
                    music_style="none",
                    nature_sound=technical_nature,
                )
                atmosphere_passport = {
                    "kind": "atmosphere",
                    "origin": "procedural_technical_draft",
                    "title": "Черновая техническая атмосфера MetroTrance",
                    "copyright_note": "Процедурный шум/имитация среды; не полевая запись",
                }
                script_warnings.append(
                    "Использована синтетическая черновая атмосфера. Для студийного результата загрузите собственную дорожку среды."
                )

            resolved_plan = sound_plan
            scene_asset_passport: list[dict] = []
            if record.request.sound_design_mode == "auto_scene":
                resolved_plan, scene_asset_passport = resolve_sound_plan(
                    sound_plan, library, job_dir, seed=job_id
                )
                script_warnings.extend(resolved_plan.warnings)

            timeline_events = [event.as_dict() for event in resolved_plan.events]
            if atmosphere_path is not None:
                import math
                atmosphere_db = 20.0 * math.log10(max(0.001, record.request.atmosphere_level / 100.0))
                timeline_events.append(
                    SoundEvent(
                        "ambience", "selected_atmosphere", 0.0, duration, atmosphere_db,
                        4.0, 8.0, 0,
                        asset_id=(atmosphere_passport or {}).get("id") if isinstance(atmosphere_passport, dict) else None,
                        asset_title=(atmosphere_passport or {}).get("title") if isinstance(atmosphere_passport, dict) else None,
                        asset_path=str(atmosphere_path),
                        asset_duration_seconds=(atmosphere_passport or {}).get("duration_seconds") if isinstance(atmosphere_passport, dict) else duration,
                    ).as_dict()
                )

            sound_plan_path = job_dir / "sound_plan.json"
            sound_plan_payload = resolved_plan.as_dict()
            sound_plan_payload["events"] = timeline_events
            sound_plan_path.write_text(
                json.dumps(sound_plan_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            if music_path is not None or timeline_events:
                self._update(job_id, progress=91, stage="Сценическое стереосведение и безопасный ducking")
                final_wav, final_mp3, final_opus = mix_scene_timeline(
                    voice_wav,
                    job_dir / "trance.wav",
                    job_dir / "trance.mp3",
                    job_dir / "trance.opus",
                    music_path=music_path,
                    music_volume=record.request.music_level / 100.0,
                    events=timeline_events,
                    mix_profile=record.request.audio_mix_profile,
                )
            else:
                self._update(job_id, progress=91, stage="Мастеринг чистого голоса без музыки")
                final_wav, final_mp3, final_opus = master_voice_only(
                    voice_wav,
                    job_dir / "trance.wav",
                    job_dir / "trance.mp3",
                    job_dir / "trance.opus",
                )

            self._update(job_id, progress=96, stage="Контроль громкости, пиков, тишины и длительности")
            audio_safety = validate_rendered_audio(final_wav, expected_seconds=duration)
            audio_safety_report_path = job_dir / "audio_safety_report.json"
            audio_safety_report_path.write_text(
                json.dumps(audio_safety.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for finding in audio_safety.findings:
                if finding.severity == "warning":
                    script_warnings.append(f"Аудиоконтроль: {finding.message}")
            if not audio_safety.ok:
                errors = "; ".join(item.message for item in audio_safety.findings if item.severity == "error")
                raise RuntimeError(f"Итоговый аудиофайл не прошёл обязательный контроль: {errors}")

            audio_passport_path = job_dir / "audio_passport.json"
            audio_passport = {
                "schema": "metrotrance.audio-passport.v2",
                "product_version": __version__,
                "voice": {
                    "origin": "user_personal_voice_profile",
                    "clone_mode": "audio_plus_exact_transcript",
                    "provider": selected_provider,
                    "human_gate": {
                        "schema": approved_choice.get("schema") if approved_choice else None,
                        "candidate_id": approved_choice.get("candidate_id") if approved_choice else None,
                        "blind_label": approved_choice.get("blind_label") if approved_choice else None,
                        "ratings": approved_choice.get("ratings") if approved_choice else None,
                        "environment_fingerprint": approved_choice.get("environment_fingerprint") if approved_choice else None,
                    },
                },
                "music": music_passport,
                "atmosphere": atmosphere_passport,
                "scene_assets": scene_asset_passport,
                "sound_plan": str(sound_plan_path),
                "safety_report": str(audio_safety_report_path),
                "mix": {
                    "profile": record.request.audio_mix_profile,
                    "music_level_percent": record.request.music_level,
                    "atmosphere_level_percent": record.request.atmosphere_level,
                    "stereo": bool(music_path or atmosphere_path),
                    "sidechain_ducking": record.request.audio_mix_profile == "studio_ducking",
                    "speech_time_stretch": False,
                    "target_loudness_lufs": -19.3,
                    "true_peak_limit_db": -1.5,
                },
                "declaration": (
                    "MetroTrance stores the user's rights declaration for imported tracks; "
                    "it does not independently verify third-party ownership."
                ),
            }
            audio_passport_path.write_text(
                json.dumps(audio_passport, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            _, _, _, _, final_duration = wav_info(final_wav)
            metadata = {
                "workflow_mode": "production",
                "tts_provider": selected_provider,
                "script_provider": script_provider,
                "content_mode": record.request.content_mode,
                "chunks": len(tts_chunks),
                "pronunciation_engine": pronunciation_results[0].engine if pronunciation_results else "none",
                "pronunciation_accents_added": sum(item.accents_added for item in pronunciation_results),
                "pronunciation_yo_added": sum(item.yo_added for item in pronunciation_results),
                "pronunciation_dictionary_hits": sum(item.dictionary_hits for item in pronunciation_results),
                "raw_speech_seconds": round(raw_speech_seconds, 2),
                "speech_tempo": 1.0,
                "voice_time_stretch": False,
                "pause_seconds": [round(value, 3) for value in pacing.pause_seconds],
                "duration_seconds": round(final_duration, 2),
                "target_duration_seconds": pacing.target_seconds,
                "duration_fit_feasible": pacing.feasible,
                "sample_rate": sample_rate,
                "voice_clone_mode": "audio_plus_exact_transcript",
                "music_mode": record.request.music_mode,
                "music_asset_id": record.request.music_asset_id,
                "atmosphere_mode": record.request.atmosphere_mode,
                "atmosphere_asset_id": record.request.atmosphere_asset_id,
                "audio_mix_profile": record.request.audio_mix_profile,
                "sound_design_mode": record.request.sound_design_mode,
                "sound_event_count": len(timeline_events),
                "audio_safety_ok": audio_safety.ok,
                "performance_profile": effective_profile,
                "performance_plan_path": str(performance_plan_path),
                "studio_reference_bank": False,
                "studio_reference_phases": sorted({cue.phase for cue in performance_plan}),
                "studio_style_family_requested": record.request.studio_style_family,
                "studio_style_family_selected": style_family_selection.selected,
                "studio_style_family_title": style_family_selection.title,
                "studio_style_source_recording": style_family_selection.source_recording,
                "studio_style_selection_reason": style_family_selection.reason,
                "expressiveness": effective_expressiveness,
                "pacing_profile": record.request.pacing_profile,
                "expected_duration_seconds": round(pacing.expected_seconds, 2),
                "audio_formats": ["wav", "mp3", "opus"],
                "tts_chunks_normalized_pcm16": True,
            }
            if effective_profile == "studio_melodic":
                script_warnings.append(
                    "Студийные записи использованы только для темпа, фаз и пауз. "
                    "Музыкальные фрагменты не передавались голосовой модели как аудиореференсы."
                )
            write_manifest(job_dir / "manifest.json", {"request": record.request.model_dump(), **metadata})
            self._update(
                job_id,
                status=JobStatus.completed,
                progress=100,
                stage="Готово",
                output_dir=str(job_dir),
                script_path=str(script_path),
                tts_script_path=str(tts_script_path),
                pronunciation_report_path=str(pronunciation_report_path),
                performance_plan_path=str(performance_plan_path),
                audio_passport_path=str(audio_passport_path),
                sound_plan_path=str(sound_plan_path),
                audio_safety_report_path=str(audio_safety_report_path),
                wav_path=str(final_wav),
                mp3_path=str(final_mp3),
                opus_path=str(final_opus),
                warnings=list(dict.fromkeys(script_warnings + tts_errors)),
                metadata=metadata,
            )
        except InterruptedError:
            return
        except Exception as exc:  # noqa: BLE001
            error_log = job_dir / "error.log"
            error_log.write_text(traceback.format_exc(), encoding="utf-8")
            self._update(job_id, status=JobStatus.failed, progress=0, stage="Ошибка", error=str(exc), output_dir=str(job_dir))
