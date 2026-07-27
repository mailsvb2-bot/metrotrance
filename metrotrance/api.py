from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from metrotrance import __version__
from metrotrance.config import Settings
from metrotrance.jobs import JobManager
from metrotrance.models import (
    JobRecord,
    PronunciationDictionaryRequest,
    PronunciationPreviewRequest,
    TranceRequest,
    VoiceApprovalRequest,
    VoiceRejectionRequest,
)
from metrotrance.providers import provider_candidates
from metrotrance.services.audio_assets import AudioAssetError, AudioAssetLibrary
from metrotrance.services.performance_director import profile_public_dict
from metrotrance.services.style_corpus import style_corpus_public_dict
from metrotrance.services.pronunciation import RussianPronunciation
from metrotrance.services.script_writer import create_script_writer
from metrotrance.services.studio_profile import load_studio_profile, recommended_word_range
from metrotrance.services.text_import import TextImportError, import_text
from metrotrance.services.voice_profile import (
    VoiceProfileError,
    assess_voice_profile,
    prepare_reference_audio,
    validate_transcript,
    write_voice_metadata,
)
from metrotrance.services.voice_quality import (
    save_voice_approval,
    save_voice_rejection,
    voice_approval_status,
)

_ALLOWED_AUDIO = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac"}
_MAX_VOICE_BYTES = 50 * 1024 * 1024
_MAX_TEXT_BYTES = 8 * 1024 * 1024
_MAX_ASSET_BYTES = 300 * 1024 * 1024


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="MetroTrance API", version=__version__, docs_url="/api/docs", redoc_url=None)
    jobs = JobManager(settings)
    static_dir = Path(__file__).parent / "static"

    @app.get("/api/ready", include_in_schema=False)
    def ready() -> dict:
        return {"ok": True, "product": "MetroTrance", "version": __version__}

    @app.get("/api/health")
    def health() -> dict:
        writer = create_script_writer(settings)
        writer_ok, writer_detail = writer.health()
        tts = []
        for provider in provider_candidates(settings):
            ok, detail = provider.health()
            tts.append({"name": provider.name, "ok": ok, "detail": detail})

        audio_ready = settings.voice_audio.exists()
        transcript_text = (
            settings.voice_transcript.read_text(encoding="utf-8").strip()
            if settings.voice_transcript.exists()
            else ""
        )
        transcript_ready = bool(transcript_text)
        voice_ready = audio_ready and transcript_ready
        metadata = {}
        if settings.voice_metadata.exists():
            try:
                metadata = json.loads(settings.voice_metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = {}
        pronunciation = RussianPronunciation(settings)
        pronunciation_ok, pronunciation_detail = pronunciation.health()
        quality_status = voice_approval_status(settings)
        voice_assessment = (
            assess_voice_profile(settings.voice_audio, transcript_text)
            if voice_ready
            else {"ok": False, "warnings": []}
        )
        return {
            "version": __version__,
            "ok": writer_ok and any(item["ok"] for item in tts) and voice_ready,
            "script": {"ok": writer_ok, "detail": writer_detail},
            "tts": tts,
            "pronunciation": {"ok": pronunciation_ok, "detail": pronunciation_detail},
            "voice_quality": quality_status,
            "voice": {
                "ok": voice_ready,
                "audio": audio_ready,
                "transcript": transcript_ready,
                "detail": (
                    "Образец и точная расшифровка сохранены"
                    if voice_ready
                    else "Нужны образец голоса и его точная расшифровка"
                ),
                "metadata": metadata,
                "assessment": voice_assessment,
            },
            "api_docs": "/api/docs",
        }


    @app.get("/api/pronunciation")
    def pronunciation_settings() -> dict:
        service = RussianPronunciation(settings)
        ok, detail = service.health()
        return {
            "ok": ok,
            "detail": detail,
            "dictionary": service.load_user_dictionary(),
            "dictionary_path": str(service.dictionary_path),
        }

    @app.post("/api/pronunciation/preview")
    def pronunciation_preview(request: PronunciationPreviewRequest) -> dict:
        result = RussianPronunciation(settings).prepare(request.text)
        return result.report()

    @app.put("/api/pronunciation/dictionary")
    def pronunciation_dictionary(request: PronunciationDictionaryRequest) -> dict:
        service = RussianPronunciation(settings)
        try:
            entries = service.save_user_dictionary(request.entries)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "dictionary": entries, "count": len(entries)}



    @app.get("/api/audio-assets")
    def list_audio_assets(kind: str | None = None) -> dict:
        try:
            assets = AudioAssetLibrary(settings).list(kind)
        except AudioAssetError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "assets": [asset.public_dict() for asset in assets]}

    @app.post("/api/audio-assets/{kind}")
    async def upload_audio_asset(
        kind: str,
        file: UploadFile = File(...),
        title: str = Form(""),
        category: str = Form("custom"),
        license_basis: str = Form(...),
        source_note: str = Form(""),
        rights_confirmed: bool = Form(...),
        tags: str = Form(""),
        safe_for_trance: bool = Form(False),
        content_reviewed: bool = Form(False),
        loopable: bool | None = Form(None),
        recommended_volume_db: float | None = Form(None),
        license_evidence: str = Form(""),
    ) -> dict:
        content = await file.read(_MAX_ASSET_BYTES + 1)
        if len(content) > _MAX_ASSET_BYTES:
            raise HTTPException(413, "Звуковая дорожка превышает 300 МБ")
        suffix = Path(file.filename or "audio.wav").suffix.lower() or ".wav"
        upload_path = settings.audio_assets_dir / f".upload-{uuid.uuid4().hex}{suffix}"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(content)
        try:
            asset = AudioAssetLibrary(settings).import_file(
                upload_path,
                original_filename=file.filename or f"{kind}{suffix}",
                kind=kind,
                title=title,
                category=category,
                license_basis=license_basis,
                source_note=source_note,
                rights_confirmed=rights_confirmed,
                tags=tags,
                safe_for_trance=safe_for_trance,
                content_reviewed=content_reviewed,
                loopable=loopable,
                recommended_volume_db=recommended_volume_db,
                license_evidence=license_evidence,
            )
        except AudioAssetError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            upload_path.unlink(missing_ok=True)
        return {"ok": True, "asset": asset.public_dict()}

    @app.delete("/api/audio-assets/{asset_id}")
    def delete_audio_asset(asset_id: str) -> dict:
        if not AudioAssetLibrary(settings).delete(asset_id):
            raise HTTPException(404, "Дорожка не найдена")
        return {"ok": True}

    @app.get("/api/studio-profile")
    def studio_profile() -> dict:
        return load_studio_profile()

    @app.get("/api/performance-profile")
    def performance_profile() -> dict:
        return profile_public_dict()

    @app.get("/api/style-corpus")
    def style_corpus() -> dict:
        return style_corpus_public_dict()

    @app.post("/api/text/import")
    async def import_text_file(file: UploadFile = File(...)) -> dict:
        content = await file.read(_MAX_TEXT_BYTES + 1)
        if len(content) > _MAX_TEXT_BYTES:
            raise HTTPException(413, "Текстовый файл превышает 8 МБ")
        try:
            text = import_text(file.filename or "text.txt", content)
        except TextImportError as exc:
            raise HTTPException(400, str(exc)) from exc
        words = len(text.split())
        return {"ok": True, "filename": file.filename or "text", "text": text, "word_count": words}

    @app.get("/api/duration-guide/{minutes}")
    def duration_guide(minutes: int) -> dict:
        if not 1 <= minutes <= 30:
            raise HTTPException(400, "Продолжительность должна быть от 1 до 30 минут")
        low, high = recommended_word_range(minutes)
        return {"minutes": minutes, "recommended_words_min": low, "recommended_words_max": high}

    @app.post("/api/voice")
    async def save_voice(
        audio: UploadFile = File(...),
        transcript: str = Form(...),
    ) -> dict:
        suffix = Path(audio.filename or "reference.wav").suffix.lower()
        if suffix not in _ALLOWED_AUDIO:
            raise HTTPException(400, "Поддерживаются WAV, MP3, FLAC, M4A и OGG")
        try:
            normalized_transcript = validate_transcript(transcript)
        except VoiceProfileError as exc:
            raise HTTPException(400, str(exc)) from exc

        content = await audio.read(_MAX_VOICE_BYTES + 1)
        if len(content) > _MAX_VOICE_BYTES:
            raise HTTPException(413, "Файл образца голоса превышает 50 МБ")
        if len(content) < 1000:
            raise HTTPException(400, "Файл образца голоса слишком мал")

        settings.voice_dir.mkdir(parents=True, exist_ok=True)
        upload_path = settings.voice_dir / f".upload-{uuid.uuid4().hex}{suffix}"
        upload_path.write_bytes(content)
        target = settings.voice_dir / "reference.wav"
        try:
            info = prepare_reference_audio(upload_path, target, min_seconds=15.0, max_seconds=60.0)
            settings.voice_transcript.write_text(normalized_transcript, encoding="utf-8")
            write_voice_metadata(settings.voice_metadata, info, normalized_transcript)
            settings.voice_quality_approval.unlink(missing_ok=True)
            (settings.voice_dir / "approved_candidate.wav").unlink(missing_ok=True)
            for old in settings.voice_dir.glob("reference.*"):
                if old != target:
                    old.unlink(missing_ok=True)
        except VoiceProfileError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            upload_path.unlink(missing_ok=True)

        return {
            "ok": True,
            "filename": target.name,
            "transcript": True,
            "duration_seconds": round(info.duration_seconds, 1),
            "sample_rate": info.sample_rate,
            "assessment": assess_voice_profile(target, normalized_transcript),
        }


    @app.get("/api/voice/quality")
    def get_voice_quality() -> dict:
        return voice_approval_status(settings)

    @app.get("/api/voice/reference")
    def download_voice_reference():
        path = settings.voice_audio
        if not path.is_file():
            raise HTTPException(404, "Образец голоса не найден")
        return FileResponse(path, media_type="audio/wav", filename="voice-reference.wav")

    @app.post("/api/voice/quality/approve")
    def approve_voice_candidate(request: VoiceApprovalRequest) -> dict:
        record = jobs.get(request.job_id)
        if record is None:
            raise HTTPException(404, "Тестовое задание не найдено")
        if record.status.value != "completed" or record.metadata.get("workflow_mode") != "voice_test":
            raise HTTPException(400, "Можно одобрить только завершённый тест голоса")
        if not request.confirm_all_listened:
            raise HTTPException(400, "Подтвердите, что прослушали все готовые варианты")
        candidates = record.metadata.get("voice_candidates") or []
        ready_ids = [str(item.get("id")) for item in candidates if item.get("status") == "ready"]
        candidate = next((item for item in candidates if item.get("id") == request.candidate_id), None)
        if candidate is None:
            raise HTTPException(404, "Кандидат голоса не найден")
        try:
            approval = save_voice_approval(
                settings,
                job_id=request.job_id,
                candidate=candidate,
                ratings=request.ratings.model_dump(),
                listened_candidate_ids=request.listened_candidate_ids,
                required_candidate_ids=ready_ids,
                notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "approval": approval, "status": voice_approval_status(settings)}

    @app.post("/api/voice/quality/reject")
    def reject_voice_candidates(request: VoiceRejectionRequest) -> dict:
        record = jobs.get(request.job_id)
        if record is None:
            raise HTTPException(404, "Тестовое задание не найдено")
        if record.status.value != "completed" or record.metadata.get("workflow_mode") != "voice_test":
            raise HTTPException(400, "Можно отклонить только завершённый тест голоса")
        if not request.confirm_all_listened:
            raise HTTPException(400, "Подтвердите, что прослушали все готовые варианты")
        candidates = record.metadata.get("voice_candidates") or []
        ready_ids = [str(item.get("id")) for item in candidates if item.get("status") == "ready"]
        try:
            feedback = save_voice_rejection(
                settings,
                job_id=request.job_id,
                listened_candidate_ids=request.listened_candidate_ids,
                required_candidate_ids=ready_ids,
                notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "feedback": feedback, "status": voice_approval_status(settings)}

    @app.get("/api/jobs/{job_id}/candidate/{candidate_id}/{kind}")
    def download_voice_candidate(job_id: str, candidate_id: str, kind: str):
        if kind not in {"mp3", "wav", "opus", "raw"}:
            raise HTTPException(400, "kind: mp3, wav, opus или raw")
        record = jobs.get(job_id)
        if record is None:
            raise HTTPException(404, "Задание не найдено")
        if record.metadata.get("workflow_mode") != "voice_test" or not record.output_dir:
            raise HTTPException(400, "Это не тест голоса")
        index_path = Path(record.output_dir) / "voice_candidates.json"
        if not index_path.is_file():
            raise HTTPException(404, "Индекс кандидатов не найден")
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(500, "Индекс кандидатов повреждён") from exc
        candidate = next(
            (item for item in payload.get("candidates", []) if item.get("id") == candidate_id),
            None,
        )
        if candidate is None:
            raise HTTPException(404, "Кандидат не найден")
        relative = (candidate.get("files") or {}).get(kind)
        if not relative:
            raise HTTPException(404, "Файл кандидата не готов")
        base = Path(record.output_dir).resolve()
        path = (base / relative).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise HTTPException(400, "Некорректный путь кандидата") from exc
        if not path.is_file():
            raise HTTPException(404, "Файл кандидата отсутствует")
        media_type = "audio/ogg" if kind == "opus" else ("audio/wav" if kind == "raw" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"))
        return FileResponse(path, media_type=media_type, filename=path.name)
    @app.post("/api/jobs", response_model=JobRecord, status_code=202)
    def create_job(request: TranceRequest) -> JobRecord:
        try:
            return jobs.create(request)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/jobs", response_model=list[JobRecord])
    def list_jobs() -> list[JobRecord]:
        return jobs.list()

    @app.get("/api/jobs/{job_id}", response_model=JobRecord)
    def get_job(job_id: str) -> JobRecord:
        record = jobs.get(job_id)
        if record is None:
            raise HTTPException(404, "Задание не найдено")
        return record

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        if not jobs.cancel(job_id):
            raise HTTPException(404, "Задание не найдено")
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/download/{kind}")
    def download(job_id: str, kind: str):
        record = jobs.get(job_id)
        if record is None:
            raise HTTPException(404, "Задание не найдено")
        choices = {
            "mp3": record.mp3_path,
            "wav": record.wav_path,
            "opus": record.opus_path,
            "script": record.script_path,
            "tts-script": record.tts_script_path,
            "pronunciation": record.pronunciation_report_path,
            "performance-plan": record.performance_plan_path,
            "passport": record.audio_passport_path,
            "sound-plan": record.sound_plan_path,
            "audio-safety": record.audio_safety_report_path,
        }
        if kind not in choices:
            raise HTTPException(400, "kind: mp3, wav, opus, script, tts-script, pronunciation, performance-plan, passport, sound-plan или audio-safety")
        path = record.safe_download_path(choices[kind])
        if path is None or not path.exists():
            raise HTTPException(404, "Файл ещё не готов")
        media_type = "audio/ogg" if kind == "opus" else ("audio/wav" if kind == "raw" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"))
        return FileResponse(path, media_type=media_type, filename=path.name)

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
