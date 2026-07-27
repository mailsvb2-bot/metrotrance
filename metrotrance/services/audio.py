from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from pathlib import Path


class AudioPipelineError(RuntimeError):
    pass


def _native_wav_info(path: Path) -> tuple[int, int, int, int, float]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
    duration = frames / sample_rate
    return channels, sample_width, sample_rate, frames, duration


def wav_info(path: Path) -> tuple[int, int, int, int, float]:
    """Read WAV metadata, including WAVE_FORMAT_EXTENSIBLE files.

    Python's standard :mod:`wave` reader rejects valid extensible WAV files with
    ``unknown format: 65534``. When that happens, FFmpeg decodes the file into a
    temporary plain PCM16 WAV and the metadata is read from that normalized copy.
    """
    try:
        return _native_wav_info(path)
    except (wave.Error, EOFError) as exc:
        with tempfile.TemporaryDirectory(prefix="metrotrance-wavinfo-") as temp_dir:
            normalized = Path(temp_dir) / "normalized.wav"
            try:
                normalize_wav_pcm16(path, normalized)
                return _native_wav_info(normalized)
            except Exception as normalize_exc:  # noqa: BLE001
                raise AudioPipelineError(f"Не удалось прочитать WAV {path.name}: {normalize_exc}") from exc


def _silence_bytes(seconds: float, channels: int, sample_width: int, sample_rate: int) -> bytes:
    frames = max(0, int(sample_rate * seconds))
    return b"\x00" * frames * channels * sample_width


def concat_wavs(
    parts: list[Path],
    output: Path,
    pause_seconds: float | list[float] | tuple[float, ...] = 1.0,
    edge_silence_seconds: float = 0.0,
    minimum_duration_seconds: float | None = None,
) -> Path:
    if not parts:
        raise AudioPipelineError("Нет аудиофрагментов для сборки")
    output.parent.mkdir(parents=True, exist_ok=True)
    first = wav_info(parts[0])
    channels, sample_width, sample_rate, _, _ = first
    edge_silence = _silence_bytes(edge_silence_seconds, channels, sample_width, sample_rate)

    if isinstance(pause_seconds, (list, tuple)):
        pauses = [max(0.0, float(value)) for value in pause_seconds]
        if len(pauses) < max(0, len(parts) - 1):
            pauses.extend([0.0] * (len(parts) - 1 - len(pauses)))
    else:
        pauses = [max(0.0, float(pause_seconds))] * max(0, len(parts) - 1)

    with wave.open(str(output), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sample_width)
        out.setframerate(sample_rate)
        if edge_silence:
            out.writeframes(edge_silence)
        for index, part in enumerate(parts):
            info = wav_info(part)
            if info[:3] != first[:3]:
                raise AudioPipelineError(f"Несовместимые параметры WAV: {part.name}")
            try:
                with wave.open(str(part), "rb") as src:
                    out.writeframes(src.readframes(src.getnframes()))
            except wave.Error as exc:
                raise AudioPipelineError(
                    f"WAV-фрагмент {part.name} не нормализован в обычный PCM16"
                ) from exc
            if index != len(parts) - 1:
                gap = _silence_bytes(pauses[index], channels, sample_width, sample_rate)
                if gap:
                    out.writeframes(gap)
        if edge_silence:
            out.writeframes(edge_silence)

        # Retained only for backwards compatibility with older smoke tests.
        if minimum_duration_seconds is not None:
            current_frames = out.getnframes()
            required_frames = int(max(0.0, minimum_duration_seconds) * sample_rate)
            if current_frames < required_frames:
                missing = required_frames - current_frames
                out.writeframes(b"\x00" * missing * channels * sample_width)
    return output


def ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise AudioPipelineError(f"FFmpeg недоступен: {exc}") from exc


def normalize_wav_pcm16(
    source: Path,
    output: Path,
    *,
    sample_rate: int = 24000,
    channels: int = 1,
) -> Path:
    """Decode any FFmpeg-readable audio into plain mono PCM16 WAV.

    This deliberately removes WAVE_FORMAT_EXTENSIBLE (format tag 65534), float
    WAV, 24/32-bit PCM and channel-layout variants before Python concatenates
    TTS chunks.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_executable(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AudioPipelineError(result.stderr.strip() or f"Не удалось нормализовать {source.name}")
    try:
        channels_out, width, rate, _, _ = _native_wav_info(output)
    except (wave.Error, EOFError) as exc:
        raise AudioPipelineError(f"FFmpeg создал некорректный PCM WAV: {output.name}") from exc
    if (channels_out, width, rate) != (channels, 2, sample_rate):
        raise AudioPipelineError(
            f"Некорректный формат после нормализации: {channels_out} каналов, {width * 8} бит, {rate} Гц"
        )
    return output


def normalize_tts_parts(parts: list[Path], output_dir: Path) -> list[Path]:
    """Normalize every TTS chunk before duration analysis and concatenation."""
    if not parts:
        raise AudioPipelineError("Нет TTS-фрагментов для нормализации")
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    for index, part in enumerate(parts):
        target = output_dir / f"chunk-{index:04d}.wav"
        normalized.append(normalize_wav_pcm16(part, target))
    return normalized


def _run_audio_exports(
    base: list[str],
    output_wav: Path,
    output_mp3: Path,
    output_opus: Path,
) -> tuple[Path, Path, Path]:
    wav_cmd = base + ["-c:a", "pcm_s16le", str(output_wav)]
    mp3_cmd = base + ["-c:a", "libmp3lame", "-b:a", "192k", str(output_mp3)]
    opus_cmd = base + [
        "-c:a",
        "libopus",
        "-b:a",
        "96k",
        "-vbr",
        "on",
        "-compression_level",
        "10",
        "-application",
        "audio",
        str(output_opus),
    ]
    for command in (wav_cmd, mp3_cmd, opus_cmd):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise AudioPipelineError(result.stderr.strip() or "FFmpeg завершился с ошибкой")
    return output_wav, output_mp3, output_opus


def mix_and_master(
    voice_wav: Path,
    ambient_wav: Path,
    output_wav: Path,
    output_mp3: Path,
    output_opus: Path,
    ambient_volume: float,
) -> tuple[Path, Path, Path]:
    ffmpeg = ffmpeg_executable()
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    *_, voice_duration = wav_info(voice_wav)
    fade_out_start = max(0.0, voice_duration - 8.0)
    filter_graph = (
        f"[0:a]volume=0.98[voice];"
        f"[1:a]volume={ambient_volume:.3f},atrim=duration={voice_duration:.3f},"
        f"afade=t=in:st=0:d=4,afade=t=out:st={fade_out_start:.3f}:d=8[bg];"
        "[voice][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "loudnorm=I=-19.3:LRA=14:TP=-2.0[out]"
    )
    base = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(voice_wav),
        "-stream_loop",
        "-1",
        "-i",
        str(ambient_wav),
        "-filter_complex",
        filter_graph,
        "-map",
        "[out]",
        "-shortest",
    ]
    return _run_audio_exports(base, output_wav, output_mp3, output_opus)


def master_voice_only(
    voice_wav: Path,
    output_wav: Path,
    output_mp3: Path,
    output_opus: Path,
) -> tuple[Path, Path, Path]:
    """Create polished voice-only WAV, MP3 and OPUS without background."""
    ffmpeg = ffmpeg_executable()
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    base = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(voice_wav),
        "-af",
        "highpass=f=55,lowpass=f=12000,loudnorm=I=-19.3:LRA=14:TP=-2.0",
    ]
    return _run_audio_exports(base, output_wav, output_mp3, output_opus)


def write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mix_studio_layers(
    voice_wav: Path,
    output_wav: Path,
    output_mp3: Path,
    output_opus: Path,
    *,
    music_path: Path | None = None,
    atmosphere_path: Path | None = None,
    music_volume: float = 0.16,
    atmosphere_volume: float = 0.10,
    mix_profile: str = "studio_ducking",
) -> tuple[Path, Path, Path]:
    """Mix a centered voice with real stereo music/atmosphere layers.

    The studio profile uses side-chain compression: background layers recede
    under speech and naturally open during trance pauses. No speech time-stretch
    or tail padding is performed here.
    """
    if music_path is None and atmosphere_path is None:
        return master_voice_only(voice_wav, output_wav, output_mp3, output_opus)
    ffmpeg = ffmpeg_executable()
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    *_, voice_duration = wav_info(voice_wav)
    fade_out_start = max(0.0, voice_duration - 8.0)

    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(voice_wav)]
    inputs: list[tuple[str, int, Path, float]] = []
    next_index = 1
    if music_path is not None:
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])
        inputs.append(("music", next_index, music_path, max(0.0, min(music_volume, 0.5))))
        next_index += 1
    if atmosphere_path is not None:
        command.extend(["-stream_loop", "-1", "-i", str(atmosphere_path)])
        inputs.append(("atmosphere", next_index, atmosphere_path, max(0.0, min(atmosphere_volume, 0.5))))

    filters = [
        "[0:a]aformat=channel_layouts=mono,highpass=f=55,lowpass=f=13000,"
        "acompressor=threshold=0.08:ratio=2:attack=25:release=350:makeup=1.25,"
        "pan=stereo|c0=c0|c1=c0,asplit=2[voice][voice_sc]"
    ]
    layer_labels: list[str] = []
    for label, index, _path, volume in inputs:
        layer = f"{label}_layer"
        filters.append(
            f"[{index}:a]aformat=channel_layouts=stereo,aresample=48000,"
            f"atrim=duration={voice_duration:.3f},asetpts=N/SR/TB,volume={volume:.4f},"
            f"afade=t=in:st=0:d=4,afade=t=out:st={fade_out_start:.3f}:d=8[{layer}]"
        )
        layer_labels.append(f"[{layer}]")

    if len(layer_labels) == 1:
        filters.append(f"{layer_labels[0]}anull[background]")
    else:
        filters.append(
            "".join(layer_labels)
            + f"amix=inputs={len(layer_labels)}:duration=first:dropout_transition=2:normalize=0[background]"
        )

    if mix_profile == "studio_ducking":
        filters.append(
            "[background][voice_sc]sidechaincompress="
            "threshold=0.025:ratio=5:attack=120:release=900:makeup=1[background_ducked]"
        )
    else:
        filters.append("[background]anull[background_ducked]")
    filters.append(
        "[voice][background_ducked]amix=inputs=2:duration=first:dropout_transition=1:normalize=0,"
        "loudnorm=I=-18.5:LRA=12:TP=-1.5[out]"
    )

    command.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "48000", "-shortest"])
    return _run_audio_exports(command, output_wav, output_mp3, output_opus)


def _db_to_linear(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)


def mix_scene_timeline(
    voice_wav: Path,
    output_wav: Path,
    output_mp3: Path,
    output_opus: Path,
    *,
    music_path: Path | None,
    music_volume: float,
    events: list[dict],
    mix_profile: str = "studio_ducking",
) -> tuple[Path, Path, Path]:
    """Render music plus timed ambience/one-shot events around a mono voice.

    Event dictionaries follow ``SoundEvent.as_dict`` and must contain a local
    ``asset_path``. Every source remains unmodified; timing, fades and levels
    are applied only in the FFmpeg graph.
    """
    if music_path is None and not events:
        return master_voice_only(voice_wav, output_wav, output_mp3, output_opus)

    ffmpeg = ffmpeg_executable()
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    *_, voice_duration = wav_info(voice_wav)
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(voice_wav)]
    input_specs: list[tuple[int, str, dict]] = []
    next_index = 1

    if music_path is not None:
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])
        input_specs.append((next_index, "music", {"start_seconds": 0.0, "end_seconds": voice_duration}))
        next_index += 1

    for event in events:
        asset_path = Path(str(event.get("asset_path", "")))
        if not asset_path.exists():
            continue
        if event.get("type") == "ambience":
            command.extend(["-stream_loop", "-1", "-i", str(asset_path)])
        else:
            command.extend(["-i", str(asset_path)])
        input_specs.append((next_index, str(event.get("type", "ambience")), event))
        next_index += 1

    filters = [
        "[0:a]aformat=channel_layouts=mono,aresample=48000,highpass=f=55,lowpass=f=13000,"
        "acompressor=threshold=0.08:ratio=2:attack=25:release=350:makeup=1.2,"
        "pan=stereo|c0=c0|c1=c0,asplit=2[voice][voice_sc]"
    ]
    labels: list[str] = []
    for index, kind, spec in input_specs:
        label = f"layer_{index}"
        start = max(0.0, float(spec.get("start_seconds", 0.0)))
        end_raw = spec.get("end_seconds")
        end = voice_duration if end_raw is None else min(voice_duration, max(start, float(end_raw)))
        duration = max(0.05, end - start)
        if kind == "one_shot":
            asset_duration = spec.get("asset_duration_seconds")
            if asset_duration is not None:
                duration = max(0.05, min(duration, float(asset_duration)))
        if kind == "music":
            volume = max(0.0, min(float(music_volume), 0.5))
            fade_in = min(12.0, duration / 3.0)
            fade_out = min(15.0, duration / 3.0)
        else:
            volume = _db_to_linear(float(spec.get("volume_db", -36.0)))
            fade_in = max(0.0, min(float(spec.get("fade_in_seconds", 1.0)), duration / 2.0))
            fade_out = max(0.0, min(float(spec.get("fade_out_seconds", 1.0)), duration / 2.0))
        delay_ms = int(round(start * 1000.0))
        chain = [
            f"[{index}:a]aformat=channel_layouts=stereo,aresample=48000",
            f"atrim=start=0:duration={duration:.3f}",
            "asetpts=N/SR/TB",
            f"volume={volume:.6f}",
        ]
        if fade_in > 0.01:
            chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0.01:
            chain.append(f"afade=t=out:st={max(0.0, duration-fade_out):.3f}:d={fade_out:.3f}")
        if delay_ms:
            chain.append(f"adelay={delay_ms}|{delay_ms}")
        filters.append(",".join(chain) + f"[{label}]")
        labels.append(f"[{label}]")

    if not labels:
        filters.append("anullsrc=r=48000:cl=stereo,atrim=duration=0.1[background]")
    elif len(labels) == 1:
        filters.append(f"{labels[0]}anull[background]")
    else:
        filters.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=2:normalize=0[background]"
        )

    if mix_profile == "studio_ducking":
        filters.append(
            "[background][voice_sc]sidechaincompress="
            "threshold=0.025:ratio=5:attack=120:release=1000:makeup=1[background_ducked]"
        )
    else:
        filters.append("[background]anull[background_ducked]")
    filters.append(
        "[voice][background_ducked]amix=inputs=2:duration=first:dropout_transition=1:normalize=0,"
        "loudnorm=I=-19.3:LRA=14:TP=-1.5[out]"
    )
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "48000", "-t", f"{voice_duration:.3f}",
    ])
    return _run_audio_exports(command, output_wav, output_mp3, output_opus)
