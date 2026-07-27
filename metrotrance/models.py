from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TranceRequest(BaseModel):
    goal: str = Field(default="", max_length=300)
    duration_minutes: int = Field(default=10, ge=1, le=30)
    address_form: str = Field(default="вы", pattern="^(ты|вы)$")
    style: str = Field(default="мягкий, спокойный, доверительный", min_length=3, max_length=300)
    ending_state: str = Field(default="спокойствие и ясность", min_length=3, max_length=200)
    extra_notes: str = Field(default="", max_length=1000)
    tts_provider: str | None = Field(
        default="auto_expressive",
        pattern="^(auto|auto_expressive|qwen|chatterbox)$",
    )

    # ai_fast: one model pass; ai_quality: plan + final script; provided_text: no script AI at all.
    content_mode: str = Field(default="ai_fast", pattern="^(ai_fast|ai_quality|provided_text)$")
    source_text: str = Field(default="", max_length=60000)

    # voice_test renders several short candidates and requires human approval.
    # production is blocked for long audio until a candidate has been approved.
    workflow_mode: str = Field(default="production", pattern="^(production|voice_test)$")

    # fit reaches the selected duration only through text and meaningful pauses.
    duration_mode: str = Field(default="fit", pattern="^(fit|natural)$")
    pacing_profile: str = Field(default="studio_reference", pattern="^(studio_reference|natural)$")

    # Performance controls. Qwen Base prioritizes cloned timbre; Chatterbox can use expressive controls.
    performance_profile: str = Field(
        default="studio_melodic",
        pattern="^(studio_melodic|warm_natural|neutral)$",
    )
    expressiveness: int = Field(default=62, ge=0, le=100)
    studio_style_family: str = Field(
        default="auto",
        pattern="^(auto|core_reference|morning_reset|evening_release|evening_sleep|agency_shift|mind_unload)$",
    )

    # New rights-aware layer selection.
    music_mode: str = Field(default="none", pattern="^(none|library|auto_library|technical_draft)$")
    music_asset_id: str | None = Field(default=None, max_length=64)
    atmosphere_mode: str = Field(default="none", pattern="^(none|library|technical_draft)$")
    atmosphere_asset_id: str | None = Field(default=None, max_length=64)
    music_level: int = Field(default=16, ge=0, le=50)
    atmosphere_level: int = Field(default=10, ge=0, le=50)
    audio_mix_profile: str = Field(default="studio_ducking", pattern="^(studio_ducking|simple)$")
    sound_design_mode: str = Field(default="auto_scene", pattern="^(none|auto_scene)$")

    # Legacy 0.1.x fields retained for loading old job.json files.
    music_style: str = Field(default="none", pattern="^(none|warm_ambient|deep_ambient|studio_morning)$")
    nature_sound: str = Field(default="none", pattern="^(none|rain|ocean|brown_noise|morning_city|forest_birds)$")
    background_level: int = Field(default=18, ge=0, le=50)

    @field_validator("goal", "style", "ending_state", "extra_notes")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("source_text")
    @classmethod
    def normalize_source_newlines(cls, value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()

    @model_validator(mode="after")
    def validate_content_source(self) -> "TranceRequest":
        if self.workflow_mode == "voice_test":
            return self
        if self.content_mode == "provided_text":
            if len(self.source_text.strip()) < 20:
                raise ValueError("Вставьте готовый текст для озвучки")
        elif len(self.goal.strip()) < 3:
            raise ValueError("Опишите цель аудиопрактики")

        # Migrate legacy requests to an explicitly labelled technical draft.
        if self.music_mode == "none" and self.music_style != "none":
            self.music_mode = "technical_draft"
        if self.atmosphere_mode == "none" and self.nature_sound != "none":
            self.atmosphere_mode = "technical_draft"
        if self.music_mode == "library" and not self.music_asset_id:
            raise ValueError("Выберите музыкальную дорожку из библиотеки")
        if self.atmosphere_mode == "library" and not self.atmosphere_asset_id:
            raise ValueError("Выберите атмосферную дорожку из библиотеки")
        return self


class PronunciationPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class PronunciationDictionaryRequest(BaseModel):
    entries: dict[str, str] = Field(default_factory=dict)


class VoiceHumanRatings(BaseModel):
    identity: int = Field(ge=1, le=5)
    naturalness: int = Field(ge=1, le=5)
    articulation: int = Field(ge=1, le=5)
    continuity: int = Field(ge=1, le=5)


class VoiceApprovalRequest(BaseModel):
    job_id: str = Field(min_length=4, max_length=64)
    candidate_id: str = Field(min_length=3, max_length=64)
    ratings: VoiceHumanRatings
    listened_candidate_ids: list[str] = Field(default_factory=list, max_length=20)
    confirm_all_listened: bool = False
    notes: str = Field(default="", max_length=500)


class VoiceRejectionRequest(BaseModel):
    job_id: str = Field(min_length=4, max_length=64)
    listened_candidate_ids: list[str] = Field(default_factory=list, max_length=20)
    confirm_all_listened: bool = False
    notes: str = Field(default="", max_length=500)


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    stage: str
    request: TranceRequest
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    output_dir: str | None = None
    script_path: str | None = None
    tts_script_path: str | None = None
    pronunciation_report_path: str | None = None
    performance_plan_path: str | None = None
    audio_passport_path: str | None = None
    sound_plan_path: str | None = None
    audio_safety_report_path: str | None = None
    wav_path: str | None = None
    mp3_path: str | None = None
    opus_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def new(cls, job_id: str, request: TranceRequest) -> "JobRecord":
        now = datetime.now(timezone.utc)
        return cls(
            id=job_id,
            status=JobStatus.queued,
            progress=0,
            stage="В очереди",
            request=request,
            created_at=now,
            updated_at=now,
        )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def safe_download_path(self, candidate: str | None) -> Path | None:
        if not candidate or not self.output_dir:
            return None
        base = Path(self.output_dir).resolve()
        path = Path(candidate).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            return None
        return path
