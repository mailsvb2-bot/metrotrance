from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx

from metrotrance.config import Settings
from metrotrance.models import TranceRequest
from metrotrance.services.local_llama import chat_completion, installation_status, shutdown_server
from metrotrance.services.studio_profile import target_words


class ScriptWriterError(RuntimeError):
    pass



STUDIO_AUTHORING_GUIDE = """
Студийная манера MetroTrance основана на пользовательском эталоне исполнения, но не копирует его текст.
Пиши не шаблонно: не начинай каждый абзац словами «прямо сейчас», «можно почувствовать» или «позвольте себе».
Чередуй короткие фразы-якоря с более длинными плавными предложениями, которые образуют одну интонационную дугу.
Выбери один центральный образ и возвращайся к нему 2–4 раза, каждый раз раскрывая новый смысл, а не повторяя формулировку.
Переходы должны вытекать из предыдущего образа, а не звучать как список инструкций.
Сначала подстройся к реальности слушателя, затем мягко углуби внимание, проведи через образ или историю,
сформулируй ключевое осознание, дай время на телесное проживание и только потом возвращай.
Паузы ставь после образов, вопросов и внутренних действий. Не заменяй живую мелодику многоточиями после каждой строки.
Избегай канцеляризма, лозунгов, повторяющихся эпитетов и одинакового синтаксиса.
"""
SYSTEM_PROMPT = """Ты профессиональный автор безопасных аудиопрактик расслабления. Пиши по-русски.
Это wellness-контент, а не медицинское лечение. Не ставь диагнозов, не обещай исцеление и гарантированный результат.
Не используй давление, запугивание, скрытое влияние, команды против воли слушателя или формулировки потери контроля.
Всегда включай мягкое начало, постепенное расслабление, основную тему, закрепление и полноценное возвращение к бодрствованию.
Текст должен звучать естественно при спокойной озвучке. Используй короткие предложения, смысловые абзацы и режиссёрские паузы.
Для пауз разрешены только маркеры: [короткая пауза], [смысловая пауза], [глубокая пауза], [интеграционная пауза].
Не ставь паузу после каждого предложения. Короткие паузы используй для дыхания, глубокие — после образов и телесных инструкций, интеграционную — перед возвращением.
Не добавляй Markdown, заголовки, списки, комментарии автора и другие служебные пометки. Выдай только готовый текст для озвучки.

""" + STUDIO_AUTHORING_GUIDE + """
Работай без режима рассуждений и не выводи внутренний анализ. /no_think"""


class ScriptWriter(ABC):
    @abstractmethod
    def generate(self, request: TranceRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> tuple[bool, str]:
        raise NotImplementedError

    def release(self) -> None:
        """Release optional model resources before speech synthesis starts."""


def target_words_for_duration(duration_minutes: int) -> int:
    return target_words(duration_minutes)


def build_user_prompt(request: TranceRequest) -> str:
    target_words = target_words_for_duration(request.duration_minutes)
    notes = request.extra_notes or "нет"
    if request.duration_minutes <= 1:
        format_instruction = (
            "Это короткий тест голоса длительностью около одной минуты. "
            "Структура: одно очень короткое предупреждение, несколько фраз расслабления, "
            "один простой образ по теме и короткое возвращение. "
            "Не делай длинного вступления, глубокого погружения, повторов или нескольких этапов. "
            "Строго уложись примерно в 70–90 слов. Добавь одну [смысловая пауза], но не делай длинной пустоты."
        )
    else:
        format_instruction = (
            "Построй драматургию студийного исполнения: подстройка к реальности, постепенное углубление, "
            "образная история или центральная метафора, ключевое осознание, телесное проживание, интеграция и мягкое возвращение. "
            "Расставь паузы осмысленно: короткие для дыхания, смысловые между этапами, "
            "глубокие после ключевых образов, одну интеграционную перед возвращением."
        )
    return f"""Создай цельную аудиопрактику.
Цель: {request.goal}
Продолжительность: примерно {request.duration_minutes} минут
Ориентир по объёму: около {target_words} слов
Обращение к слушателю: на «{request.address_form}»
Манера: {request.style}
Желаемое состояние в конце: {request.ending_state}
Дополнительные пожелания: {notes}

{format_instruction}
Начни с короткого предупреждения не слушать за рулём. Не используй слова «гипноз», «лечение» и «терапия» внутри самой записи без необходимости. /no_think"""


def _max_tokens(request: TranceRequest) -> int:
    # The one-minute test must remain short even if the model tends to elaborate.
    if request.duration_minutes <= 1:
        return 280
    # Russian text often uses more model tokens per word than English. Leave
    # enough headroom for the target duration while staying inside 8K context.
    target_words = target_words_for_duration(request.duration_minutes)
    return min(6200, max(1200, int(target_words * 2.2)))


def _minimum_script_chars(request: TranceRequest) -> int:
    return 80 if request.duration_minutes <= 1 else 200


class LocalLlamaWriter(ScriptWriter):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> tuple[bool, str]:
        return installation_status(self.settings)

    def generate(self, request: TranceRequest) -> str:
        try:
            if request.duration_minutes <= 1 or request.content_mode == "ai_fast":
                # Fast mode uses one model pass. Quality mode keeps the two-pass
                # plan + final-script workflow for longer practices.
                content = chat_completion(
                    self.settings,
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(request)},
                    ],
                    _max_tokens(request),
                )
            else:
                plan = chat_completion(
                    self.settings,
                    [
                        {
                            "role": "system",
                            "content": (
                                "Ты редактор аудиопрактик. Составь внутренний подробный план: "
                                "этапы, переходы, распределение объёма, вариативные образы и "
                                "полноценный выход. Не пиши готовую запись. /no_think"
                            ),
                        },
                        {"role": "user", "content": build_user_prompt(request)},
                    ],
                    900,
                )
                final_prompt = (
                    build_user_prompt(request)
                    + "\n\nИспользуй этот редакторский план, но не показывай его слушателю:\n"
                    + plan
                    + "\n\nТеперь выдай только цельный готовый текст для озвучки. /no_think"
                )
                content = chat_completion(
                    self.settings,
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": final_prompt},
                    ],
                    _max_tokens(request),
                )
        except Exception as exc:  # noqa: BLE001
            raise ScriptWriterError(str(exc)) from exc
        if len(content) < _minimum_script_chars(request):
            raise ScriptWriterError("Локальная модель вернула слишком короткий сценарий")
        return content

    def release(self) -> None:
        shutdown_server(self.settings)


class OllamaWriter(ScriptWriter):
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_url
        self.model = settings.ollama_model

    def health(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                response = client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            models = [item.get("name", "") for item in response.json().get("models", [])]
            present = self.model in models or any(name.startswith(f"{self.model}:") for name in models)
            if not present:
                return False, f"Ollama работает, но модель {self.model} не загружена"
            return True, f"Ollama: {self.model}"
        except Exception:  # noqa: BLE001
            return False, "Ollama не запущена"

    def generate(self, request: TranceRequest) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
            "options": {
                "temperature": 0.72,
                "top_p": 0.9,
                "num_ctx": 8192,
                "num_predict": _max_tokens(request),
            },
        }
        try:
            with httpx.Client(timeout=900.0, trust_env=False) as client:
                response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "").strip()
        except Exception as exc:  # noqa: BLE001
            raise ScriptWriterError(f"Ошибка Ollama: {exc}") from exc
        if len(content) < _minimum_script_chars(request):
            raise ScriptWriterError("Модель вернула слишком короткий сценарий")
        return content


class OpenAICompatibleWriter(ScriptWriter):
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.openai_url
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model

    def health(self) -> tuple[bool, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                response = client.get(f"{self.base_url}/models", headers=headers)
            response.raise_for_status()
            return True, f"OpenAI-compatible API: {self.model}"
        except Exception:  # noqa: BLE001
            return False, "OpenAI-compatible API недоступен"

    def generate(self, request: TranceRequest) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "temperature": 0.72,
            "max_tokens": _max_tokens(request),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
        }
        try:
            with httpx.Client(timeout=900.0, trust_env=False) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, json.JSONDecodeError, httpx.HTTPError) as exc:
            raise ScriptWriterError(f"Ошибка OpenAI-compatible API: {exc}") from exc
        if len(content) < _minimum_script_chars(request):
            raise ScriptWriterError("Модель вернула слишком короткий сценарий")
        return content


def create_script_writer(settings: Settings) -> ScriptWriter:
    if settings.script_provider in {"llama_cpp", "local", "local_llama"}:
        return LocalLlamaWriter(settings)
    if settings.script_provider == "ollama":
        return OllamaWriter(settings)
    if settings.script_provider == "openai_compatible":
        return OpenAICompatibleWriter(settings)
    raise ScriptWriterError(f"Неизвестный SCRIPT_PROVIDER: {settings.script_provider}")
