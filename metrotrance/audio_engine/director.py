from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from metrotrance.services.audio_assets import AudioAsset, AudioAssetLibrary, copy_asset_for_job
from .models import SoundEvent, SoundPlan


def _pick(assets: list[AudioAsset], seed: str, category: str) -> AudioAsset | None:
    if not assets:
        return None
    digest = hashlib.sha256(f"{seed}:{category}".encode("utf-8")).digest()
    return assets[int.from_bytes(digest[:4], "big") % len(assets)]


def select_auto_music(library: AudioAssetLibrary, *, seed: str, preferred_categories: list[str]) -> AudioAsset | None:
    for category in preferred_categories + ["relaxation", "warm", "deep", "neutral", "custom"]:
        assets = library.find_safe(kind="music", category=category)
        picked = _pick(assets, seed, category)
        if picked:
            return picked
    return None


def resolve_sound_plan(
    plan: SoundPlan,
    library: AudioAssetLibrary,
    job_dir: Path,
    *,
    seed: str,
) -> tuple[SoundPlan, list[dict]]:
    cache: dict[str, tuple[AudioAsset, Path]] = {}
    resolved: list[SoundEvent] = []
    warnings = list(plan.warnings)
    passport: list[dict] = []

    for event in plan.events:
        kind = "atmosphere" if event.type == "ambience" else "event"
        key = f"{kind}:{event.category}"
        chosen: AudioAsset | None = None
        local_path: Path | None = None
        if key in cache:
            chosen, local_path = cache[key]
        else:
            candidates = library.find_safe(kind=kind, category=event.category)
            chosen = _pick(candidates, seed, key)
            if chosen:
                local_path = copy_asset_for_job(library, chosen, job_dir)
                cache[key] = (chosen, local_path)
                passport.append(chosen.public_dict())

        if not chosen or not local_path:
            warnings.append(
                f"Нет вручную проверенного звука категории «{event.category}»; сцена оставлена без этого слоя."
            )
            continue

        # Library metadata has the final say about safe baseline level/fades.
        resolved.append(
            replace(
                event,
                volume_db=min(event.volume_db, chosen.recommended_volume_db),
                fade_in_seconds=max(event.fade_in_seconds, chosen.fade_in_seconds),
                fade_out_seconds=max(event.fade_out_seconds, chosen.fade_out_seconds),
                asset_id=chosen.id,
                asset_title=chosen.title,
                asset_path=str(local_path),
                asset_duration_seconds=chosen.duration_seconds,
            )
        )

    unique_warnings = tuple(dict.fromkeys(warnings))
    return SoundPlan(plan.duration_seconds, plan.mode, tuple(resolved), unique_warnings), passport
