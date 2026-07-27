from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from metrotrance.config import Settings
from metrotrance.services.audio import ffmpeg_executable, wav_info

AssetKind = Literal["music", "atmosphere", "event"]

_ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac"}
_ALLOWED_LICENSES = {
    "owned_exclusive",
    "licensed_commercial",
    "public_domain_cc0",
    "commissioned_with_rights",
    "pixabay_content_license",
}
_ALLOWED_CATEGORIES = {
    "sleep", "relaxation", "morning", "deep", "warm", "neutral", "nature",
    "city", "rain", "ocean", "forest", "birds", "metro", "cafe", "room",
    "fire", "stream", "horn", "car_passing", "doors", "footsteps", "custom",
}


class AudioAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioAsset:
    id: str
    kind: AssetKind
    title: str
    category: str
    stored_filename: str
    original_filename: str
    duration_seconds: float
    sample_rate: int
    channels: int
    sha256: str
    license_basis: str
    source_note: str
    rights_confirmed: bool
    imported_at: str
    tags: tuple[str, ...] = ()
    safe_for_trance: bool = False
    content_reviewed: bool = False
    loopable: bool = False
    recommended_volume_db: float = -34.0
    fade_in_seconds: float = 4.0
    fade_out_seconds: float = 7.0
    license_evidence: str = ""

    def public_dict(self) -> dict:
        payload = asdict(self)
        payload["duration_seconds"] = round(self.duration_seconds, 2)
        payload["recommended_volume_db"] = round(self.recommended_volume_db, 2)
        payload["tags"] = list(self.tags)
        return payload


class AudioAssetLibrary:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.audio_assets_dir
        self.index_path = self.root / "index.json"
        self.music_dir = self.root / "music"
        self.atmosphere_dir = self.root / "atmosphere"
        self.event_dir = self.root / "event"
        for directory in (self.root, self.music_dir, self.atmosphere_dir, self.event_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_kind(kind: str) -> AssetKind:
        if kind not in {"music", "atmosphere", "event"}:
            raise AudioAssetError("Тип дорожки должен быть music, atmosphere или event")
        return kind  # type: ignore[return-value]

    def _load_raw(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AudioAssetError(f"Повреждён индекс звуковой библиотеки: {exc}") from exc
        if not isinstance(data, list):
            raise AudioAssetError("Некорректный формат индекса звуковой библиотеки")
        return [item for item in data if isinstance(item, dict)]

    def _save_raw(self, items: list[dict]) -> None:
        temp = self.index_path.with_suffix(".tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.index_path)

    @staticmethod
    def _from_dict(item: dict) -> AudioAsset:
        kind = str(item["kind"])
        default_loopable = kind in {"music", "atmosphere"}
        default_db = -30.0 if kind == "music" else (-34.0 if kind == "atmosphere" else -41.0)
        tags_raw = item.get("tags", [])
        tags = tuple(str(value).strip().lower() for value in tags_raw if str(value).strip()) if isinstance(tags_raw, list) else ()
        return AudioAsset(
            id=str(item["id"]), kind=kind, title=str(item["title"]),  # type: ignore[arg-type]
            category=str(item.get("category", "custom")), stored_filename=str(item["stored_filename"]),
            original_filename=str(item.get("original_filename", item["stored_filename"])),
            duration_seconds=float(item["duration_seconds"]), sample_rate=int(item.get("sample_rate", 48000)),
            channels=int(item.get("channels", 2)), sha256=str(item["sha256"]),
            license_basis=str(item["license_basis"]), source_note=str(item.get("source_note", "")),
            rights_confirmed=bool(item.get("rights_confirmed", False)), imported_at=str(item["imported_at"]),
            tags=tags, safe_for_trance=bool(item.get("safe_for_trance", False)),
            content_reviewed=bool(item.get("content_reviewed", False)),
            loopable=bool(item.get("loopable", default_loopable)),
            recommended_volume_db=float(item.get("recommended_volume_db", default_db)),
            fade_in_seconds=float(item.get("fade_in_seconds", 4.0)),
            fade_out_seconds=float(item.get("fade_out_seconds", 7.0)),
            license_evidence=str(item.get("license_evidence", "")),
        )

    def list(self, kind: str | None = None) -> list[AudioAsset]:
        normalized_kind = self._validate_kind(kind) if kind else None
        assets: list[AudioAsset] = []
        for raw in self._load_raw():
            try:
                asset = self._from_dict(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if normalized_kind and asset.kind != normalized_kind:
                continue
            if self.path_for(asset).exists():
                assets.append(asset)
        return sorted(assets, key=lambda item: item.imported_at, reverse=True)

    def get(self, asset_id: str, *, kind: str | None = None) -> AudioAsset | None:
        return next((asset for asset in self.list(kind) if asset.id == asset_id), None)

    def find_safe(self, *, kind: str, category: str) -> list[AudioAsset]:
        category = category.lower().strip()
        return [
            asset for asset in self.list(kind)
            if asset.rights_confirmed and asset.content_reviewed and asset.safe_for_trance
            and (asset.category == category or category in asset.tags)
        ]

    def path_for(self, asset: AudioAsset) -> Path:
        directory = {"music": self.music_dir, "atmosphere": self.atmosphere_dir, "event": self.event_dir}[asset.kind]
        return directory / asset.stored_filename

    @staticmethod
    def _safe_title(value: str, fallback: str) -> str:
        cleaned = " ".join(value.split()).strip() or fallback
        return cleaned[:120]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _normalize_to_flac(source: Path, output: Path, *, kind: AssetKind) -> tuple[float, int, int]:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="metrotrance-asset-") as temp_dir:
            probe_wav = Path(temp_dir) / "probe.wav"
            command = [
                ffmpeg_executable(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(probe_wav),
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise AudioAssetError(result.stderr.strip() or "FFmpeg не смог прочитать аудиофайл")
            channels, _, sample_rate, _, duration = wav_info(probe_wav)
            minimum = 0.25 if kind == "event" else 5.0
            if duration < minimum:
                raise AudioAssetError(f"Дорожка должна быть длиннее {minimum:g} секунды")
            maximum = 120.0 if kind == "event" else 6 * 60 * 60
            if duration > maximum:
                raise AudioAssetError("Разовый звук длиннее 2 минут" if kind == "event" else "Дорожка длиннее 6 часов")
            encode = [
                ffmpeg_executable(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(probe_wav),
                "-c:a", "flac", "-compression_level", "8", str(output),
            ]
            result = subprocess.run(encode, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise AudioAssetError(result.stderr.strip() or "Не удалось сохранить дорожку в библиотеку")
        return duration, sample_rate, channels

    @staticmethod
    def _tags(value: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
        raw = value if isinstance(value, (list, tuple)) else re.split(r"[,;\n]+", value)
        cleaned = []
        for item in raw:
            tag = re.sub(r"\s+", "_", str(item).strip().lower().replace("ё", "е"))
            if tag and re.fullmatch(r"[а-яa-z0-9_-]{2,40}", tag):
                cleaned.append(tag)
        return tuple(dict.fromkeys(cleaned))[:30]

    def import_file(
        self, source: Path, *, original_filename: str, kind: str, title: str, category: str,
        license_basis: str, source_note: str, rights_confirmed: bool,
        tags: str | list[str] | tuple[str, ...] = (), safe_for_trance: bool = False,
        content_reviewed: bool = False, loopable: bool | None = None,
        recommended_volume_db: float | None = None, license_evidence: str = "",
    ) -> AudioAsset:
        normalized_kind = self._validate_kind(kind)
        suffix = Path(original_filename).suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise AudioAssetError("Поддерживаются WAV, MP3, FLAC, M4A, OGG, OPUS и AAC")
        if not rights_confirmed:
            raise AudioAssetError("Подтвердите право использовать эту дорожку")
        if license_basis not in _ALLOWED_LICENSES:
            raise AudioAssetError("Выберите допустимое основание использования")
        if category not in _ALLOWED_CATEGORIES:
            category = "custom"
        if not source.exists() or source.stat().st_size < 1000:
            raise AudioAssetError("Аудиофайл пуст или повреждён")
        if safe_for_trance and not content_reviewed:
            raise AudioAssetError("Перед отметкой «безопасно для транса» прослушайте файл полностью")
        if license_basis in {"licensed_commercial", "pixabay_content_license"} and not (source_note.strip() or license_evidence.strip()):
            raise AudioAssetError("Для сторонней лицензии сохраните ссылку, сертификат или номер договора")

        default_db = -30.0 if normalized_kind == "music" else (-34.0 if normalized_kind == "atmosphere" else -41.0)
        db = default_db if recommended_volume_db is None else max(-60.0, min(float(recommended_volume_db), -12.0))
        loop = normalized_kind != "event" if loopable is None else bool(loopable)
        if normalized_kind == "event":
            loop = False

        asset_id = uuid.uuid4().hex[:16]
        directory = {"music": self.music_dir, "atmosphere": self.atmosphere_dir, "event": self.event_dir}[normalized_kind]
        stored_filename = f"{asset_id}.flac"
        target = directory / stored_filename
        try:
            duration, sample_rate, channels = self._normalize_to_flac(source, target, kind=normalized_kind)
            fallback = re.sub(r"[_-]+", " ", Path(original_filename).stem).strip() or "Без названия"
            asset = AudioAsset(
                id=asset_id, kind=normalized_kind, title=self._safe_title(title, fallback), category=category,
                stored_filename=stored_filename, original_filename=Path(original_filename).name[:220],
                duration_seconds=duration, sample_rate=sample_rate, channels=channels, sha256=self._sha256(target),
                license_basis=license_basis, source_note=" ".join(source_note.split())[:1000],
                rights_confirmed=True, imported_at=datetime.now(timezone.utc).isoformat(), tags=self._tags(tags),
                safe_for_trance=bool(safe_for_trance), content_reviewed=bool(content_reviewed), loopable=loop,
                recommended_volume_db=db, fade_in_seconds=4.0 if normalized_kind != "event" else 0.25,
                fade_out_seconds=7.0 if normalized_kind != "event" else 0.8,
                license_evidence=" ".join(license_evidence.split())[:1000],
            )
            items = self._load_raw(); items.append(asset.public_dict()); self._save_raw(items)
            return asset
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def delete(self, asset_id: str) -> bool:
        items = self._load_raw(); retained: list[dict] = []; removed: AudioAsset | None = None
        for raw in items:
            try:
                asset = self._from_dict(raw)
            except (KeyError, TypeError, ValueError):
                retained.append(raw); continue
            if asset.id == asset_id: removed = asset
            else: retained.append(raw)
        if removed is None: return False
        self.path_for(removed).unlink(missing_ok=True); self._save_raw(retained); return True

    def passport_entry(self, asset_id: str | None, *, kind: str) -> dict | None:
        if not asset_id: return None
        asset = self.get(asset_id, kind=kind)
        if asset is None: raise AudioAssetError(f"Дорожка {kind} не найдена в библиотеке")
        payload = asset.public_dict(); payload["local_path"] = str(self.path_for(asset)); return payload


def copy_asset_for_job(library: AudioAssetLibrary, asset: AudioAsset, job_dir: Path) -> Path:
    source = library.path_for(asset)
    if not source.exists(): raise AudioAssetError(f"Файл дорожки «{asset.title}» отсутствует")
    target_dir = job_dir / "source_assets"; target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{asset.kind}-{asset.id}.flac"
    try: os.link(source, target)
    except OSError: shutil.copy2(source, target)
    return target
