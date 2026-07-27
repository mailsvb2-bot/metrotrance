from __future__ import annotations

import hashlib
import importlib.util
import inspect
import threading
from pathlib import Path

from metrotrance.config import Settings


class QwenTTSError(RuntimeError):
    pass


class QwenTTSProvider:
    name = "qwen"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._prompt = None
        self._prompt_key: str | None = None
        self._lock = threading.RLock()

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("qwen_tts") is not None and importlib.util.find_spec("torch") is not None

    def release(self) -> None:
        """Release model memory between calibration engines/jobs."""
        self._model = None
        self._prompt = None
        self._prompt_key = None
        try:
            import gc
            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def health(self) -> tuple[bool, str]:
        if not self.installed():
            return False, "Qwen3-TTS не установлен"
        return True, f"Qwen3-TTS: {self.settings.qwen_tts_model}"

    def _resolve_device(self):
        import torch

        requested = self.settings.qwen_tts_device
        if requested != "auto":
            return requested
        return "cuda:0" if torch.cuda.is_available() else "cpu"

    def _load(self):
        if self._model is not None:
            return self._model
        import torch
        from qwen_tts import Qwen3TTSModel

        device = self._resolve_device()
        kwargs = {"device_map": device}
        if device.startswith("cuda"):
            kwargs["dtype"] = torch.bfloat16
            if importlib.util.find_spec("flash_attn") is not None:
                kwargs["attn_implementation"] = "flash_attention_2"
        else:
            kwargs["dtype"] = torch.float32
        try:
            self._model = Qwen3TTSModel.from_pretrained(self.settings.qwen_tts_model, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise QwenTTSError(f"Не удалось загрузить Qwen3-TTS: {exc}") from exc
        return self._model

    @staticmethod
    def _make_prompt_key(reference_audio: Path, transcript: str) -> str:
        stat = reference_audio.stat()
        payload = f"{reference_audio.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{transcript}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _voice_prompt(self, reference_audio: Path, transcript: str):
        transcript = transcript.strip()
        if not transcript:
            raise QwenTTSError(
                "Для клонирования Qwen требуется точная расшифровка образца голоса. "
                "Режим только по отпечатку голоса отключён из-за низкого качества."
            )
        key = self._make_prompt_key(reference_audio, transcript)
        if self._prompt is not None and self._prompt_key == key:
            return self._prompt
        model = self._load()
        try:
            self._prompt = model.create_voice_clone_prompt(
                ref_audio=str(reference_audio),
                ref_text=transcript,
                x_vector_only_mode=False,
            )
            self._prompt_key = key
        except Exception as exc:  # noqa: BLE001
            raise QwenTTSError(f"Не удалось обработать образец голоса: {exc}") from exc
        return self._prompt

    def _generation_kwargs(
        self,
        model,
        performance: dict | None = None,
        cue: dict | None = None,
    ) -> dict:
        performance = performance or {}
        cue = cue or {}
        profile = str(performance.get("profile", "warm_natural"))
        expressiveness = max(0, min(int(cue.get("expressiveness", performance.get("expressiveness", 55))), 100))
        if profile == "studio_melodic":
            temperature = float(cue.get("temperature", 0.54 + 0.0012 * expressiveness))
            top_p = 0.82
            top_k = 30
        elif profile == "neutral":
            temperature = 0.48
            top_p = 0.80
            top_k = 24
        else:
            temperature = 0.58 + 0.0010 * expressiveness
            top_p = 0.86
            top_k = 34
        candidates = {
            "do_sample": True,
            "top_k": top_k,
            "top_p": top_p,
            "temperature": temperature,
            "repetition_penalty": 1.06,
            "subtalker_dosample": True,
            "subtalker_top_k": top_k,
            "subtalker_top_p": top_p,
            "subtalker_temperature": temperature,
        }
        try:
            signature = inspect.signature(model.generate_voice_clone)
        except (TypeError, ValueError):
            return candidates
        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
            return candidates
        return {key: value for key, value in candidates.items() if key in signature.parameters}

    def synthesize_chunks(
        self,
        chunks: list[str],
        output_dir: Path,
        reference_audio: Path,
        transcript: str,
        performance: dict | None = None,
    ) -> list[Path]:
        import soundfile as sf
        import torch

        output_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            model = self._load()
            prompt = self._voice_prompt(reference_audio, transcript)
            cue_values = (performance or {}).get("cues") or []
            paths: list[Path] = []
            seed_base = int((performance or {}).get("seed", 0))
            for index, text in enumerate(chunks, start=1):
                cue = cue_values[index - 1] if index - 1 < len(cue_values) else None
                generation_kwargs = self._generation_kwargs(model, performance, cue)
                chunk_seed = (seed_base + index * 1009) % (2**31 - 1)
                cuda_devices = []
                if self._resolve_device().startswith("cuda") and torch.cuda.is_available():
                    cuda_devices = list(range(torch.cuda.device_count()))
                try:
                    with torch.random.fork_rng(devices=cuda_devices):
                        torch.manual_seed(chunk_seed)
                        if torch.cuda.is_available():
                            torch.cuda.manual_seed_all(chunk_seed)
                        wavs, sample_rate = model.generate_voice_clone(
                            text=text,
                            language="Russian",
                            voice_clone_prompt=prompt,
                            **generation_kwargs,
                        )
                except TypeError:
                    # Compatibility with older qwen-tts builds that do not expose
                    # all sampling parameters yet.
                    try:
                        with torch.random.fork_rng(devices=cuda_devices):
                            torch.manual_seed(chunk_seed)
                            if torch.cuda.is_available():
                                torch.cuda.manual_seed_all(chunk_seed)
                            wavs, sample_rate = model.generate_voice_clone(
                                text=text,
                                language="Russian",
                                voice_clone_prompt=prompt,
                            )
                    except Exception as exc:  # noqa: BLE001
                        raise QwenTTSError(f"Ошибка синтеза Qwen3-TTS на фрагменте {index}: {exc}") from exc
                except Exception as exc:  # noqa: BLE001
                    raise QwenTTSError(f"Ошибка синтеза Qwen3-TTS на фрагменте {index}: {exc}") from exc
                path = output_dir / f"chunk_{index:03d}.wav"
                sf.write(str(path), wavs[0], sample_rate, subtype="PCM_16")
                paths.append(path)
            return paths
