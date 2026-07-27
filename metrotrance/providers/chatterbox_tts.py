from __future__ import annotations

import importlib.util
import inspect
import threading
from pathlib import Path

from metrotrance.config import Settings


class ChatterboxTTSError(RuntimeError):
    pass


class ChatterboxTTSProvider:
    name = "chatterbox"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._lock = threading.RLock()

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("chatterbox") is not None and importlib.util.find_spec("torchaudio") is not None

    def release(self) -> None:
        """Release model memory between calibration engines/jobs."""
        self._model = None
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
            return False, "Chatterbox не установлен"
        return True, "Chatterbox Multilingual — только чистый голосовой референс"

    def _resolve_device(self) -> str:
        import torch

        requested = self.settings.chatterbox_device
        if requested != "auto":
            return requested
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @staticmethod
    def _loader_accepts(loader, parameter: str) -> bool:
        """Return True when a callable explicitly accepts a parameter or **kwargs.

        Chatterbox changed the ``from_pretrained`` signature between releases.
        Older builds accept only ``device`` while current multilingual V3 builds
        also accept ``t3_model``. MetroTrance supports both instead of coupling
        the application to one exact package version.
        """
        try:
            signature = inspect.signature(loader)
        except (TypeError, ValueError):
            return False
        return parameter in signature.parameters or any(
            item.kind == inspect.Parameter.VAR_KEYWORD
            for item in signature.parameters.values()
        )

    def _load(self):
        if self._model is not None:
            return self._model
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        loader = ChatterboxMultilingualTTS.from_pretrained
        kwargs = {"device": self._resolve_device()}
        if self._loader_accepts(loader, "t3_model"):
            kwargs["t3_model"] = "v3"

        try:
            self._model = loader(**kwargs)
        except TypeError as exc:
            # Some distributions expose an imprecise signature but still reject
            # the V3 selector at runtime. Retry once with the legacy API.
            if "t3_model" in kwargs and "t3_model" in str(exc):
                kwargs.pop("t3_model", None)
                try:
                    self._model = loader(**kwargs)
                except Exception as retry_exc:  # noqa: BLE001
                    raise ChatterboxTTSError(
                        f"Не удалось загрузить Chatterbox: {retry_exc}"
                    ) from retry_exc
            else:
                raise ChatterboxTTSError(f"Не удалось загрузить Chatterbox: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ChatterboxTTSError(f"Не удалось загрузить Chatterbox: {exc}") from exc
        return self._model

    def synthesize_chunks(
        self,
        chunks: list[str],
        output_dir: Path,
        reference_audio: Path,
        transcript: str,
        performance: dict | None = None,
    ) -> list[Path]:
        del transcript
        performance = performance or {}
        profile = str(performance.get("profile", "warm_natural"))
        expressiveness = max(0, min(int(performance.get("expressiveness", 55)), 100))
        cue_values = performance.get("cues") or []

        def parameters_for(chunk_index: int) -> tuple[float, float, float, Path]:
            cue = cue_values[chunk_index] if chunk_index < len(cue_values) else {}
            if profile == "studio_melodic" and cue:
                exaggeration = float(cue.get("exaggeration", 0.60))
                cfg_weight = float(cue.get("cfg_weight", 0.34))
                temperature = float(cue.get("temperature", 0.69))
            elif profile == "studio_melodic":
                exaggeration = min(0.72, 0.52 + expressiveness / 500.0)
                cfg_weight = 0.28
                temperature = 0.72
            elif profile == "neutral":
                exaggeration = 0.42
                cfg_weight = 0.50
                temperature = 0.65
            else:
                exaggeration = min(0.64, 0.46 + expressiveness / 650.0)
                cfg_weight = 0.34
                temperature = 0.70

            # Studio masters with music/reverb are never used as prompts.
            # They may inform pacing elsewhere, but the voice model sees only
            # the user's clean, transcript-matched reference recording.
            prompt = reference_audio
            if not prompt.is_file():
                raise ChatterboxTTSError("Не найден чистый образец голоса")
            return exaggeration, cfg_weight, temperature, prompt

        import torch
        import torchaudio as ta

        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        with self._lock:
            model = self._load()
            seed_base = int(performance.get("seed", 0))
            for zero_index, text in enumerate(chunks):
                index = zero_index + 1
                exaggeration, cfg_weight, temperature, prompt = parameters_for(zero_index)
                chunk_seed = (seed_base + index * 1009) % (2**31 - 1)
                try:
                    candidates = {
                        "language_id": "ru",
                        "audio_prompt_path": str(prompt),
                        "exaggeration": exaggeration,
                        "cfg_weight": cfg_weight,
                        "temperature": temperature,
                    }
                    try:
                        signature = inspect.signature(model.generate)
                        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
                            candidates = {k: v for k, v in candidates.items() if k in signature.parameters}
                    except (TypeError, ValueError):
                        pass
                    cuda_devices = list(range(torch.cuda.device_count())) if torch.cuda.is_available() else []
                    with torch.random.fork_rng(devices=cuda_devices):
                        torch.manual_seed(chunk_seed)
                        if torch.cuda.is_available():
                            torch.cuda.manual_seed_all(chunk_seed)
                        wav = model.generate(text, **candidates)
                except Exception as exc:  # noqa: BLE001
                    raise ChatterboxTTSError(f"Ошибка синтеза Chatterbox: {exc}") from exc
                path = output_dir / f"chunk_{index:03d}.wav"
                ta.save(str(path), wav, model.sr)
                paths.append(path)
        return paths
