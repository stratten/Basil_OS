"""Log-mel feature extractor for NVIDIA Parakeet TDT 0.6B v2 (ONNX path).

The Parakeet preprocessor parameters are pinned to match the NeMo
``AudioToMelSpectrogramPreprocessor`` block that the released
``parakeet-tdt-0.6b-v2`` model was trained with. The community ONNX
bundle (``istupakov/parakeet-tdt-0.6b-v2-onnx``) ships a
``preprocessor_config.yaml`` whose values mirror the constants below; we
hard-code the defaults here so the bundle works out of the box and only
fall back to YAML overrides when one is present (different community
re-exports occasionally tweak ``log_zero_guard_value``).

Shape contract returned by :meth:`ParakeetFeatureExtractor.compute`:

    features: ``np.float32`` ``[1, n_mels, T]`` -- per-feature mean/var
              normalized log-mel spectrogram in NeMo's native layout.
              ``n_mels`` is 128 for ``parakeet-tdt-0.6b-v2`` (see
              :class:`FeatureParams` for the full rationale).
    length:   ``np.int64`` ``[1]``               -- ``T`` (number of mel
              frames). The Parakeet encoder reads this as the
              valid-frame count for masking.

Why librosa? It's already a direct dep of Basil (``pyproject.toml``
``librosa = "^0.10.1"``) and is what the existing HuggingFace Whisper
path uses to load audio in :mod:`transcription_processor`. Reusing it
avoids pulling in another spectrogram dependency just for Parakeet.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

try:
    import librosa
except ImportError as exc:  # pragma: no cover - librosa is a hard dep
    raise ImportError(
        "librosa is required for Parakeet feature extraction. "
        "It should already be installed via Basil's pyproject.toml."
    ) from exc

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore


@dataclass(frozen=True)
class FeatureParams:
    """Parakeet preprocessor parameters.

    Matches the NeMo ``AudioToMelSpectrogramPreprocessor`` defaults that
    ``parakeet-tdt-0.6b-v2`` was trained with. The named attributes
    correspond directly to keys in NeMo's preprocessor YAML so swapping
    in an override file from a different community export is a 1:1
    mapping.
    """

    sample_rate: int = 16000
    # Parakeet TDT 0.6B v2 was trained with NeMo's 128-mel FastConformer
    # preprocessor (NVIDIA's ``parakeet-tdt-0.6b-v2`` model card lists
    # ``features: 128`` under the ``AudioToMelSpectrogramPreprocessor``
    # init params, and the istupakov ONNX bundle ships an explicit
    # ``nemo128.onnx`` preprocessor module whose name encodes the bin
    # count). Feeding 80-bin features to the encoder produces a
    # ``Got: 80 Expected: 128`` ``onnxruntime.InvalidArgument`` at run
    # time, which is silent until the first transcription is attempted
    # (the encoder ONNX session loads fine because its input shape is
    # symbolic). The istupakov bundle does NOT ship a
    # ``preprocessor_config.yaml`` either, so the
    # ``from_preprocessor_yaml`` auto-detect path in
    # :class:`ParakeetFeatureExtractor` cannot recover this value at
    # runtime -- the default below has to be correct.
    n_mels: int = 128
    n_fft: int = 512
    win_length_samples: int = 400  # 25 ms at 16 kHz.
    hop_length_samples: int = 160  # 10 ms at 16 kHz.
    f_min: float = 0.0
    f_max: float = 8000.0  # Nyquist for 16 kHz audio.
    pre_emphasis: float = 0.97
    # Power-of-two clip on the mel energies before log; matches NeMo's
    # ``log_zero_guard_value=2**-24`` and prevents -inf for silent frames.
    log_zero_guard: float = float(2 ** -24)
    # Per-feature mean/var normalization across the time axis is the
    # default for FastConformer encoders; ``per_feature`` below.
    normalize: str = "per_feature"


DEFAULT_FEATURE_PARAMS = FeatureParams()


class ParakeetFeatureExtractor:
    """Stateless log-mel feature extractor for Parakeet (128-dim by default).

    A single instance can be reused across calls and across threads --
    nothing here is mutated after construction.
    """

    def __init__(self, params: Optional[FeatureParams] = None):
        self.params = params or DEFAULT_FEATURE_PARAMS

        # Pre-compute the mel filterbank once. ``librosa.filters.mel``
        # returns shape ``[n_mels, 1 + n_fft // 2]``; we keep it as
        # float32 to avoid an upcast during the matmul.
        self._mel_basis: np.ndarray = librosa.filters.mel(
            sr=self.params.sample_rate,
            n_fft=self.params.n_fft,
            n_mels=self.params.n_mels,
            fmin=self.params.f_min,
            fmax=self.params.f_max,
        ).astype(np.float32)

        # onnx-asr's NemoPreprocessor pads a 400-sample Hann window out to
        # n_fft before STFT. Matching that keeps weak-speech bins aligned
        # with the exported Parakeet encoder.
        side_pad = (self.params.n_fft - self.params.win_length_samples) // 2
        self._window: np.ndarray = np.pad(
            np.hanning(self.params.win_length_samples).astype(np.float32),
            (side_pad, side_pad),
        ).astype(np.float32, copy=False)

    @classmethod
    def from_preprocessor_yaml(cls, yaml_path: Path) -> "ParakeetFeatureExtractor":
        """Build an extractor whose params come from a NeMo preprocessor YAML.

        Use this when the ONNX bundle ships a ``preprocessor_config.yaml``
        whose values differ from the v2 defaults (rare but possible for
        community re-exports). Falls back to defaults for any key the
        YAML does not specify.
        """
        if yaml is None:
            return cls()
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                cfg: Dict[str, Any] = yaml.safe_load(f) or {}
        except Exception:
            return cls()

        # NeMo nests the preprocessor under ``preprocessor`` / ``init_params``.
        nested = (
            cfg.get("preprocessor", {}).get("init_params", {})
            if isinstance(cfg.get("preprocessor"), dict)
            else cfg
        )
        defaults = asdict(DEFAULT_FEATURE_PARAMS)
        merged = {
            "sample_rate": int(nested.get("sample_rate", defaults["sample_rate"])),
            "n_mels": int(nested.get("features", defaults["n_mels"])),
            "n_fft": int(nested.get("n_fft", defaults["n_fft"])),
            # NeMo uses seconds; convert to samples when present.
            "win_length_samples": int(
                round(
                    float(nested.get("window_size", 0.025))
                    * int(nested.get("sample_rate", defaults["sample_rate"]))
                )
            ),
            "hop_length_samples": int(
                round(
                    float(nested.get("window_stride", 0.010))
                    * int(nested.get("sample_rate", defaults["sample_rate"]))
                )
            ),
            "f_min": float(nested.get("lowfreq", defaults["f_min"])),
            "f_max": float(nested.get("highfreq", defaults["f_max"])),
            "pre_emphasis": float(nested.get("preemph", defaults["pre_emphasis"])),
            "log_zero_guard": float(
                nested.get("log_zero_guard_value", defaults["log_zero_guard"])
            ),
            "normalize": str(nested.get("normalize", defaults["normalize"])),
        }
        return cls(FeatureParams(**merged))

    def _apply_pre_emphasis(self, audio: np.ndarray) -> np.ndarray:
        """Apply first-order pre-emphasis filter ``y[n] = x[n] - a*x[n-1]``."""
        if self.params.pre_emphasis <= 0.0:
            return audio
        out = np.empty_like(audio)
        out[0] = audio[0]
        out[1:] = audio[1:] - self.params.pre_emphasis * audio[:-1]
        return out

    def _per_feature_normalize(
        self,
        mel_log: np.ndarray,
        valid_frames: int,
    ) -> np.ndarray:
        """Normalize each mel bin to zero mean / unit variance over time.

        Matches NeMo's ``normalize="per_feature"`` mode (default for
        FastConformer). Computed independently per mel bin so a noisy
        background does not bleed into clean bins.
        """
        # mel_log: [n_mels, T]
        total_frames = mel_log.shape[1]
        valid_frames = min(max(1, valid_frames), total_frames)
        mask = np.arange(total_frames) < valid_frames
        valid = mel_log[:, mask]
        mean = valid.mean(axis=1, keepdims=True)
        if valid_frames > 1:
            variance = np.sum((valid - mean) ** 2, axis=1, keepdims=True) / (valid_frames - 1)
        else:
            variance = np.zeros((mel_log.shape[0], 1), dtype=mel_log.dtype)
        normalized = (mel_log - mean) / (np.sqrt(variance) + 1e-5)
        normalized[:, ~mask] = 0.0
        return normalized

    def compute(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Compute log-mel features and the frame count for one utterance.

        Args:
            audio: 1-D ``np.ndarray`` of float samples in ``[-1.0, 1.0]``,
                already resampled to :attr:`FeatureParams.sample_rate`
                (16 kHz). The caller is expected to have used
                ``librosa.load(..., sr=16000, mono=True)`` or equivalent.

        Returns:
            ``(features, length)`` where ``features`` has shape
            ``[1, n_mels, T]`` and ``length`` has shape ``[1]``. ``T`` is
            the number of mel frames after the STFT.
        """
        if audio.ndim != 1:
            audio = np.asarray(audio).reshape(-1)
        audio = audio.astype(np.float32, copy=False)

        if audio.size == 0:
            # Empty audio -- emit a single silent frame so the encoder
            # has a valid input rather than crashing on a zero-length
            # tensor.
            empty = np.zeros((1, self.params.n_mels, 1), dtype=np.float32)
            return empty, np.asarray([1], dtype=np.int64)

        signal = self._apply_pre_emphasis(audio)

        # onnx-asr's exported Nemo preprocessor zero-pads by n_fft//2 and
        # then performs STFT without reflect-centered padding.
        padded_signal = np.pad(
            signal,
            (self.params.n_fft // 2, self.params.n_fft // 2),
            mode="constant",
        )
        stft = librosa.stft(
            padded_signal,
            n_fft=self.params.n_fft,
            hop_length=self.params.hop_length_samples,
            win_length=self.params.n_fft,
            window=self._window,
            center=False,
        )
        # Power spectrogram.
        power = (stft.real ** 2 + stft.imag ** 2).astype(np.float32)

        mel = self._mel_basis @ power  # [n_mels, T]
        mel_log = np.log(mel + self.params.log_zero_guard)

        length = np.asarray([features_length := mel_log.shape[1]], dtype=np.int64)
        if self.params.normalize == "per_feature":
            mel_log = self._per_feature_normalize(mel_log, features_length)

        # Reshape to NeMo's [B, n_mels, T] convention used by the ONNX
        # encoder's ``audio_signal`` input.
        features = mel_log[np.newaxis, :, :].astype(np.float32, copy=False)
        return features, length
