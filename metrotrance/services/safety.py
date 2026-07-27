from __future__ import annotations

import re
from dataclasses import dataclass


class UnsafeRequestError(ValueError):
    pass


@dataclass(frozen=True)
class SafetyResult:
    text: str
    warnings: list[str]


_BLOCKED_PATTERNS = [
    (re.compile(r"\b(самоубий|суицид|убить себя|навредить себе)\w*", re.I), "самоповреждение"),
    (re.compile(r"\b(убить|отравить|напасть|взорвать)\b", re.I), "причинение вреда"),
    (re.compile(r"\bбез согласия\b|\bпротив (?:его|её|их) воли\b", re.I), "воздействие без согласия"),
]

_MEDICAL_REPLACEMENTS = [
    (re.compile(r"\b(?:полностью\s+)?вылеч(?:ит|ивает|ишь|итесь)\b", re.I), "может поддержать ощущение спокойствия"),
    (re.compile(r"\bгарантированно избав(?:ит|ляет|ишь|итесь)\b", re.I), "может помочь мягко поработать"),
    (re.compile(r"\bисцел(?:ит|яет|ишь|итесь)\b", re.I), "поддержит внутреннее восстановление"),
]


def validate_goal(goal: str) -> None:
    for pattern, reason in _BLOCKED_PATTERNS:
        if pattern.search(goal):
            raise UnsafeRequestError(f"Запрос отклонён: обнаружена тема «{reason}».")


def enforce_safety(text: str, *, compact: bool = False) -> SafetyResult:
    warnings: list[str] = []
    result = text.strip()
    for pattern, replacement in _MEDICAL_REPLACEMENTS:
        result, count = pattern.subn(replacement, result)
        if count:
            warnings.append("Удалены категоричные медицинские обещания.")

    intro = (
        "Не слушайте эту запись за рулём или при управлении техникой."
        if compact
        else (
            "Перед началом убедитесь, что вы находитесь в безопасном месте. "
            "Не слушайте эту запись за рулём, при управлении техникой или там, где требуется постоянное внимание."
        )
    )
    if "за рул" not in result.lower() and "управлен" not in result.lower():
        result = f"{intro}\n\n{result}"
        warnings.append("Добавлено обязательное предупреждение о безопасности.")

    exit_markers = ("откройте глаза", "вернитесь", "возвращайтесь", "ощутите комнату")
    if not any(marker in result.lower() for marker in exit_markers):
        if compact:
            result += (
                "\n\nСделайте глубокий вдох, почувствуйте опору и, когда будете готовы, откройте глаза."
            )
        else:
            result += (
                "\n\nА теперь постепенно возвращайтесь к обычному бодрствованию. "
                "Почувствуйте опору под телом, сделайте более глубокий вдох, мягко пошевелите пальцами "
                "и, когда будете готовы, откройте глаза, сохраняя спокойствие и ясность."
            )
        warnings.append("Добавлен безопасный выход из практики.")

    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return SafetyResult(result, list(dict.fromkeys(warnings)))
