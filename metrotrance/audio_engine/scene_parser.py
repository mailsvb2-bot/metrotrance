from __future__ import annotations

import re
from dataclasses import dataclass

from .models import SceneCue

_EXPLICIT = re.compile(
    r"\[(?P<action>звук|атмосфера|стоп|событие)\s*:\s*(?P<category>[а-яёa-z0-9_-]+)\]",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(?:не|нет|без|переста(?:ёт|ет|ли|ло)|утиха(?:ет|ют)|исчеза(?:ет|ют)|больше\s+не)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SceneRule:
    category: str
    keywords: tuple[str, ...]
    event_type: str = "ambience"


RULES: tuple[SceneRule, ...] = (
    SceneRule("metro", ("метро", "вагон", "станци", "платформ", "поезд")),
    SceneRule("rain", ("дожд", "капл", "мокр", "ливень")),
    SceneRule("city", ("город", "улиц", "дорог", "автомобил", "машин")),
    SceneRule("forest", ("лес", "дерев", "поляна", "листв")),
    SceneRule("birds", ("птиц", "щебет", "пение птиц")),
    SceneRule("ocean", ("море", "берег", "волны", "прибой")),
    SceneRule("cafe", ("кафе", "кофейн", "чашк")),
    SceneRule("room", ("комнат", "домашн", "кресл", "кровать")),
    SceneRule("fire", ("костёр", "костер", "огонь", "пламя")),
    SceneRule("stream", ("ручей", "река", "вода теч")),
    SceneRule("horn", ("клаксон", "автомобильный сигнал"), "one_shot"),
    SceneRule("car_passing", ("проезжает автомобиль", "машина проезжает"), "one_shot"),
    SceneRule("doors", ("двери открываются", "двери закрываются"), "one_shot"),
    SceneRule("footsteps", ("шаги", "идёте", "идете"), "one_shot"),
)

_ALIAS = {
    "море": "ocean",
    "волны": "ocean",
    "лес": "forest",
    "птицы": "birds",
    "город": "city",
    "метро": "metro",
    "вагон": "metro",
    "дождь": "rain",
    "клаксон": "horn",
    "машина": "car_passing",
    "двери": "doors",
    "шаги": "footsteps",
    "комната": "room",
    "кафе": "cafe",
    "костёр": "fire",
    "костер": "fire",
    "ручей": "stream",
}


class SceneParser:
    """Rule-based scene parser with explicit commands and local negation handling.

    It deliberately avoids cloud AI and does not pretend to understand every
    metaphor. Low-confidence matches only create suggestions; the renderer uses
    them when a matching, manually approved local asset exists.
    """

    def parse_segments(self, texts: list[str]) -> list[SceneCue]:
        cues: list[SceneCue] = []
        seen_ambience: set[str] = set()
        for index, original in enumerate(texts):
            text = original.lower().replace("ё", "е")
            explicit_spans: list[tuple[int, int]] = []
            for match in _EXPLICIT.finditer(original):
                explicit_spans.append(match.span())
                action_raw = match.group("action").lower()
                category_raw = match.group("category").lower().replace("ё", "е")
                category = _ALIAS.get(category_raw, category_raw)
                if action_raw == "стоп":
                    action = "stop"
                elif action_raw == "событие":
                    action = "one_shot"
                else:
                    action = "start"
                cues.append(SceneCue(action, category, index, 1.0, match.group(0)))
                if action == "start":
                    seen_ambience.add(category)
                elif action == "stop":
                    seen_ambience.discard(category)

            clean = _EXPLICIT.sub(" ", text)
            for rule in RULES:
                hit = next((keyword for keyword in rule.keywords if keyword.replace("ё", "е") in clean), None)
                if not hit:
                    continue
                pos = clean.find(hit.replace("ё", "е"))
                local = clean[max(0, pos - 40) : pos + len(hit) + 25]
                negated = bool(_NEGATION.search(local))
                if rule.event_type == "one_shot":
                    if not negated:
                        cues.append(SceneCue("one_shot", rule.category, index, 0.78, hit))
                    continue
                if negated:
                    if rule.category in seen_ambience:
                        cues.append(SceneCue("stop", rule.category, index, 0.84, local.strip()))
                        seen_ambience.discard(rule.category)
                elif rule.category not in seen_ambience:
                    cues.append(SceneCue("start", rule.category, index, 0.72, hit))
                    seen_ambience.add(rule.category)
        return cues
