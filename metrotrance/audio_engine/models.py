from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

EventType = Literal["ambience", "one_shot"]
CueAction = Literal["start", "stop", "one_shot", "intensity"]


@dataclass(frozen=True)
class SceneCue:
    action: CueAction
    category: str
    segment_index: int
    confidence: float
    source: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SoundEvent:
    type: EventType
    category: str
    start_seconds: float
    end_seconds: float | None
    volume_db: float
    fade_in_seconds: float
    fade_out_seconds: float
    source_segment: int
    asset_id: str | None = None
    asset_title: str | None = None
    asset_path: str | None = None
    asset_duration_seconds: float | None = None

    def as_dict(self) -> dict:
        payload = asdict(self)
        for key in ("start_seconds", "end_seconds", "volume_db", "fade_in_seconds", "fade_out_seconds"):
            value = payload.get(key)
            if isinstance(value, float):
                payload[key] = round(value, 3)
        return payload


@dataclass(frozen=True)
class SoundPlan:
    duration_seconds: float
    mode: str
    events: tuple[SoundEvent, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "schema": "metrotrance.sound-plan.v1",
            "duration_seconds": round(self.duration_seconds, 3),
            "mode": self.mode,
            "events": [event.as_dict() for event in self.events],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SafetyFinding:
    code: str
    severity: Literal["info", "warning", "error"]
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SafetyReport:
    ok: bool
    duration_seconds: float
    max_volume_dbfs: float | None
    mean_volume_dbfs: float | None
    long_silence_seconds: float
    findings: tuple[SafetyFinding, ...]

    def as_dict(self) -> dict:
        return {
            "schema": "metrotrance.audio-safety.v1",
            "ok": self.ok,
            "duration_seconds": round(self.duration_seconds, 3),
            "max_volume_dbfs": self.max_volume_dbfs,
            "mean_volume_dbfs": self.mean_volume_dbfs,
            "long_silence_seconds": round(self.long_silence_seconds, 3),
            "findings": [item.as_dict() for item in self.findings],
        }
