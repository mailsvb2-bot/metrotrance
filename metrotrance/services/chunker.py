from __future__ import annotations

import re
from dataclasses import dataclass

from metrotrance.services.studio_profile import pause_default

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_EXPLICIT_PAUSE = re.compile(
    r"\[(?:(короткая|смысловая|глубокая|длинная|интеграционная)\s+)?пауза"
    r"(?:\s*[:=]?\s*(\d+(?:[.,]\d+)?))?\s*(?:с|сек|сек\.|секунд[аы]?)?\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpeechSegment:
    text: str
    pause_after: float
    pause_kind: str


def chunk_text(text: str, max_chars: int = 520, min_chars: int = 90) -> list[str]:
    return [segment.text for segment in segment_text(text, max_chars=max_chars, min_chars=min_chars)]


def _default_pause_for_text(text: str, paragraph_end: bool, profile: str) -> tuple[float, str]:
    stripped = text.rstrip()
    if profile == "natural":
        if paragraph_end:
            return 1.8, "paragraph"
        if stripped.endswith(("…", "...")):
            return 1.2, "ellipsis"
        if stripped.endswith("?"):
            return 1.0, "question"
        return 0.65, "sentence"

    if paragraph_end:
        return pause_default("paragraph"), "paragraph"
    if stripped.endswith(("…", "...")):
        return pause_default("ellipsis"), "ellipsis"
    if stripped.endswith("?"):
        return pause_default("question"), "question"
    return pause_default("sentence"), "sentence"


def _explicit_pause_seconds(kind: str | None, raw_seconds: str | None) -> tuple[float, str]:
    if raw_seconds:
        value = float(raw_seconds.replace(",", "."))
        return max(0.3, min(value, 60.0)), "explicit_exact"
    normalized = (kind or "").lower()
    mapping = {
        "короткая": (pause_default("short"), "explicit_short"),
        "смысловая": (pause_default("semantic"), "explicit_semantic"),
        "глубокая": (pause_default("deep"), "explicit_deep"),
        "длинная": (6.5, "explicit_long"),
        "интеграционная": (pause_default("integration"), "explicit_integration"),
    }
    return mapping.get(normalized, (pause_default("semantic"), "explicit_semantic"))


def segment_text(
    text: str,
    max_chars: int = 520,
    min_chars: int = 90,
    profile: str = "studio_reference",
) -> list[SpeechSegment]:
    """Split text into TTS-friendly chunks and preserve trance pause boundaries.

    Supported markers:
      [короткая пауза]        -> about 0.7 s
      [смысловая пауза]       -> about 2 s
      [глубокая пауза]        -> about 5.5 s
      [интеграционная пауза]  -> about 10 s
      [пауза 8]               -> exactly 8 s (capped at 60)
    """
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []

    marker_index = 0
    marker_values: dict[str, tuple[float, str]] = {}

    def replace_marker(match: re.Match[str]) -> str:
        nonlocal marker_index
        marker_index += 1
        token = f"§§PAUSE_{marker_index}§§"
        marker_values[token] = _explicit_pause_seconds(match.group(1), match.group(2))
        return f"\n\n{token}\n\n"

    marked = _EXPLICIT_PAUSE.sub(replace_marker, cleaned)
    blocks = [block.strip() for block in re.split(r"\n\s*\n", marked) if block.strip()]
    segments: list[SpeechSegment] = []

    def append_text_chunk(value: str, paragraph_end: bool) -> None:
        pause, kind = _default_pause_for_text(value, paragraph_end, profile)
        segments.append(SpeechSegment(value.strip(), pause, kind))

    for block in blocks:
        if block in marker_values:
            if segments:
                pause, kind = marker_values[block]
                previous = segments[-1]
                segments[-1] = SpeechSegment(previous.text, pause, kind)
            continue

        paragraph = " ".join(block.split())
        sentences = _SENTENCE_END.split(paragraph)
        chunks: list[str] = []
        current = ""

        def flush() -> None:
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
            current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            parts = [sentence]
            if len(sentence) > max_chars:
                parts = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
            for part in parts:
                candidate = f"{current} {part}".strip() if current else part
                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    flush()
                    if len(part) <= max_chars:
                        current = part
                    else:
                        for start in range(0, len(part), max_chars):
                            piece = part[start : start + max_chars].strip()
                            if piece:
                                chunks.append(piece)
        flush()

        if len(chunks) > 1 and len(chunks[-1]) < min_chars:
            merged = f"{chunks[-2]} {chunks[-1]}".strip()
            if len(merged) <= max_chars + min_chars:
                chunks[-2:] = [merged]

        for index, chunk in enumerate(chunks):
            append_text_chunk(chunk, paragraph_end=index == len(chunks) - 1)

    if segments:
        last = segments[-1]
        segments[-1] = SpeechSegment(last.text, 0.0, "end")
    return segments
