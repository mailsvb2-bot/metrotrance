from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path


_ALLOWED_MUSIC = {"none", "warm_ambient", "deep_ambient", "studio_morning"}
_ALLOWED_NATURE = {"none", "rain", "ocean", "brown_noise", "morning_city", "forest_birds"}


def generate_ambient_wav(
    output: Path,
    duration_seconds: float,
    sample_rate: int = 24000,
    seed: int = 42,
    music_style: str = "studio_morning",
    nature_sound: str = "morning_city",
) -> Path:
    """Generate a reusable ambient bed.

    Long recordings use a three-minute bed which FFmpeg loops underneath the
    complete voice track. This avoids spending many minutes synthesizing 30
    minutes of background sample-by-sample on an older CPU.
    """
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if music_style not in _ALLOWED_MUSIC:
        raise ValueError("unknown music_style")
    if nature_sound not in _ALLOWED_NATURE:
        raise ValueError("unknown nature_sound")

    tile_seconds = min(float(duration_seconds), 180.0)
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    total_frames = int(tile_seconds * sample_rate)

    if music_style == "deep_ambient":
        base_freqs = (43.65, 65.41, 87.31, 130.81)
        tone_gain = 0.085
        lfo_hz = 0.018
        pulse_gain = 0.012
    elif music_style == "studio_morning":
        base_freqs = (49.0, 73.42, 98.0, 146.83, 196.0)
        tone_gain = 0.075
        lfo_hz = 0.028
        pulse_gain = 0.020
    elif music_style == "warm_ambient":
        base_freqs = (55.0, 82.5, 110.0, 164.8)
        tone_gain = 0.090
        lfo_hz = 0.035
        pulse_gain = 0.010
    else:
        base_freqs = (55.0,)
        tone_gain = 0.0
        lfo_hz = 0.035
        pulse_gain = 0.0

    phases = [rng.random() * math.tau for _ in base_freqs]
    smooth_noise = 0.0
    brown = 0.0
    ocean_state = 0.0
    city_state = 0.0

    # Sparse synthetic bird events. They are deliberately quiet and distant.
    bird_events: list[tuple[float, float, float]] = []
    if nature_sound in {"morning_city", "forest_birds"}:
        event_time = 2.0 + rng.random() * 3.0
        interval = (3.5, 8.0) if nature_sound == "forest_birds" else (7.0, 16.0)
        while event_time < tile_seconds:
            bird_events.append((event_time, rng.uniform(1450.0, 2900.0), rng.uniform(0.18, 0.42)))
            event_time += rng.uniform(*interval)

    bird_index = 0
    active_birds: list[tuple[float, float, float]] = []

    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        buffer = bytearray()

        for i in range(total_frames):
            t = i / sample_rate
            slow = 0.58 + 0.18 * math.sin(math.tau * lfo_hz * t)
            tone = 0.0
            if tone_gain:
                for idx, freq in enumerate(base_freqs):
                    tone += math.sin(math.tau * freq * t + phases[idx]) / (idx + 2.3)

            # A subtle pulse gives the studio-morning bed direction without
            # becoming a literal metronome.
            pulse = 0.0
            if pulse_gain:
                pulse_envelope = max(0.0, math.sin(math.tau * 0.92 * t)) ** 5
                pulse = pulse_envelope * math.sin(math.tau * 49.0 * t)

            white = rng.uniform(-1.0, 1.0)
            smooth_noise = 0.985 * smooth_noise + 0.015 * white
            nature = 0.0

            if nature_sound == "rain":
                droplet = rng.uniform(-1.0, 1.0) if rng.random() < 0.0022 else 0.0
                nature = 0.048 * white + 0.045 * smooth_noise + 0.015 * droplet
            elif nature_sound == "ocean":
                ocean_state = 0.996 * ocean_state + 0.004 * white
                swell = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(math.tau * 0.075 * t))
                nature = 0.12 * ocean_state * swell + 0.016 * smooth_noise
            elif nature_sound == "brown_noise":
                brown = max(-1.0, min(1.0, brown + white * 0.018))
                brown *= 0.9985
                nature = 0.080 * brown
            elif nature_sound == "morning_city":
                city_state = 0.998 * city_state + 0.002 * white
                distant_traffic = 0.055 * city_state + 0.012 * math.sin(math.tau * 31.0 * t)
                nature = distant_traffic + 0.010 * smooth_noise
            elif nature_sound == "forest_birds":
                nature = 0.012 * smooth_noise
            elif music_style != "none":
                nature = 0.018 * smooth_noise

            while bird_index < len(bird_events) and bird_events[bird_index][0] <= t:
                active_birds.append(bird_events[bird_index])
                bird_index += 1
            if active_birds:
                active_birds = [event for event in active_birds if t - event[0] <= event[2]]

            birds = 0.0
            for start, frequency, length in active_birds:
                local = t - start
                envelope = math.sin(math.pi * local / length) ** 2
                sweep = frequency * (1.0 + 0.20 * local / length)
                birds += 0.035 * envelope * math.sin(math.tau * sweep * local)

            sample = tone_gain * tone * slow + pulse_gain * pulse + nature + birds
            sample = max(-0.88, min(0.88, sample))
            buffer.extend(struct.pack("<h", int(sample * 32767)))
            if len(buffer) >= 65536:
                wav.writeframesraw(buffer)
                buffer.clear()
        if buffer:
            wav.writeframesraw(buffer)
    return output
