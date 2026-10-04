"""Basil Parakeet probe with diagnostic decoder coverage metrics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from api.services.transcription.backends.parakeet_components.parakeet_decoder import (
    DEFAULT_FRAME_STRIDE_SEC,
    MAX_SYMBOLS_PER_STEP,
    ParakeetToken,
    _build_decoder_inputs,
    _classify_decoder_outputs,
    _seed_zero_decoder_states,
    _softmax_argmax,
    detokenize_pieces,
    pieces_to_words,
)
from api.services.transcription.backends.parakeet_service import (
    ParakeetTranscriptionService,
)
from api.services.transcription.backends.parakeet_components.parakeet_adaptive_transcription import (
    run_adaptive_parakeet_transcription,
)
from api.services.transcription.processing.audio_utils import rms_normalize_audio

from .audio_coverage import load_mono_audio
from .models import BackendRunResult, BasilDecoderDiagnostics, build_backend_result


DEFAULT_BASIL_PARAKEET_MODEL = "NVIDIA-parakeet-tdt-0.6b-v3-quantized"


@dataclass
class BasilParakeetPipelineResult:
    text: str
    diagnostics: BasilDecoderDiagnostics


def load_basil_conditioned_audio(audio_path: Path) -> np.ndarray:
    audio, _ = load_mono_audio(audio_path)
    if audio.size == 0:
        return audio
    original_rms = float(np.sqrt(np.mean(audio * audio)))
    if original_rms > 1e-8:
        return rms_normalize_audio(audio).astype(np.float32, copy=False)
    return audio.astype(np.float32, copy=False)


def run_basil_parakeet_probe(
    audio_path: Path,
    *,
    model_id: str = DEFAULT_BASIL_PARAKEET_MODEL,
) -> BackendRunResult:
    started_at = monotonic()
    try:
        service = ParakeetTranscriptionService(model_id=model_id)
        service.load_model()
        audio = load_basil_conditioned_audio(audio_path)
        pipeline_result = run_basil_parakeet_pipeline_with_diagnostics(service, audio)
        return build_backend_result(
            backend="basil_parakeet_production_conditioned",
            model_id=model_id,
            success=True,
            wall_seconds=monotonic() - started_at,
            text=pipeline_result.text,
            diagnostics=pipeline_result.diagnostics,
        )
    except Exception as exc:
        return build_backend_result(
            backend="basil_parakeet_production_conditioned",
            model_id=model_id,
            success=False,
            wall_seconds=monotonic() - started_at,
            error=f"{type(exc).__name__}: {exc}",
        )


def run_basil_parakeet_adaptive_probe(
    audio_path: Path,
    *,
    model_id: str = DEFAULT_BASIL_PARAKEET_MODEL,
) -> BackendRunResult:
    started_at = monotonic()
    try:
        service = ParakeetTranscriptionService(model_id=model_id)
        service.load_model()
        audio, sample_rate = load_mono_audio(audio_path)
        adaptive_result = run_adaptive_parakeet_transcription(
            audio,
            sample_rate=sample_rate,
            infer_transcript=service._infer_pipeline_transcript,
            force_adaptive=True,
        )
        return build_backend_result(
            backend="basil_parakeet_adaptive",
            model_id=model_id,
            success=True,
            wall_seconds=monotonic() - started_at,
            text=adaptive_result.text,
            metadata={
                "selected_strategy": adaptive_result.selected_strategy,
                "baseline_suspect": adaptive_result.baseline_suspect,
                "selected_coverage_score": adaptive_result.selected_run.coverage.coverage_score,
                "runs": [
                    {
                        "strategy": run.strategy,
                        "coverage_score": run.coverage.coverage_score,
                        "word_count": run.coverage.word_count,
                        "text_chars": run.coverage.text_chars,
                        "reasons": run.coverage.reasons,
                    }
                    for run in adaptive_result.runs
                ],
            },
        )
    except Exception as exc:
        return build_backend_result(
            backend="basil_parakeet_adaptive",
            model_id=model_id,
            success=False,
            wall_seconds=monotonic() - started_at,
            error=f"{type(exc).__name__}: {exc}",
        )


def run_basil_parakeet_pipeline_with_diagnostics(
    service: ParakeetTranscriptionService,
    audio: np.ndarray,
) -> BasilParakeetPipelineResult:
    if service._feature_extractor is None:
        service._feature_extractor = service._build_feature_extractor()

    encoder_session = service._model_manager.encoder_session
    decoder_session = service._model_manager.decoder_session
    if encoder_session is None or decoder_session is None:
        raise RuntimeError("Parakeet ONNX sessions are not loaded")

    features, feature_length = service._feature_extractor.compute(audio)
    encoder_inputs = service._build_encoder_feed(features, feature_length)
    encoder_output_names = service._model_manager.encoder_io[1]
    encoder_outputs = encoder_session.run(encoder_output_names, encoder_inputs)
    outputs_by_name = dict(zip(encoder_output_names, encoder_outputs))
    encoder_hidden, encoded_lengths = service._extract_encoder_outputs(
        outputs_by_name,
        fallback_length=int(feature_length[0]),
    )

    tokens, decoder_diagnostics = trace_tdt_greedy_decode(
        encoder_hidden,
        encoded_lengths,
        decoder_session,
        vocab=service._model_manager.vocab,
        blank_id=service._model_manager.blank_id,
        durations=service._model_manager.durations,
        decoder_input_names=service._model_manager.decoder_io[0],
        decoder_output_names=service._model_manager.decoder_io[1],
    )
    text = detokenize_pieces(tokens)
    words = pieces_to_words(tokens)
    decoder_diagnostics.features_shape = list(features.shape)
    decoder_diagnostics.feature_length = int(feature_length[0])
    decoder_diagnostics.encoder_hidden_shape = list(encoder_hidden.shape)
    decoder_diagnostics.encoded_length = int(encoded_lengths[0])
    decoder_diagnostics.piece_count = len(tokens)
    decoder_diagnostics.word_count = len(words)
    decoder_diagnostics.text_chars = len(text)
    if words:
        decoder_diagnostics.first_word_seconds = round(words[0].start_sec, 3)
        decoder_diagnostics.last_word_seconds = round(words[-1].end_sec, 3)
        decoder_diagnostics.word_span_seconds = round(
            max(0.0, words[-1].end_sec - words[0].start_sec),
            3,
        )
    return BasilParakeetPipelineResult(text=text, diagnostics=decoder_diagnostics)


def trace_tdt_greedy_decode(
    encoder_outputs: np.ndarray,
    encoded_lengths: np.ndarray,
    decoder_session,
    vocab: Sequence[str],
    blank_id: int,
    *,
    durations: Optional[Sequence[int]] = None,
    frame_stride_sec: float = DEFAULT_FRAME_STRIDE_SEC,
    decoder_input_names: Optional[Sequence[str]] = None,
    decoder_output_names: Optional[Sequence[str]] = None,
) -> Tuple[List[ParakeetToken], BasilDecoderDiagnostics]:
    if encoder_outputs.ndim != 3 or encoder_outputs.shape[0] != 1:
        raise ValueError(f"Expected encoder_outputs shape [1, D, T], got {encoder_outputs.shape}")

    t_total = min(int(encoded_lengths[0]), int(encoder_outputs.shape[2]))
    diagnostics = BasilDecoderDiagnostics(encoder_frames=t_total)
    if t_total <= 0:
        return [], diagnostics

    if decoder_input_names is None:
        decoder_input_names = [item.name for item in decoder_session.get_inputs()]
    if decoder_output_names is None:
        decoder_output_names = [item.name for item in decoder_session.get_outputs()]

    joint_out, state_outs = _classify_decoder_outputs(decoder_output_names)
    if joint_out is None:
        raise RuntimeError(f"Could not identify joint logits output among {decoder_output_names}")

    n_dur = len(durations) if durations is not None else 0
    decoder_states: Dict[str, np.ndarray] = _seed_zero_decoder_states(decoder_session)
    input_state_names = list(decoder_states.keys())

    tokens: List[ParakeetToken] = []
    last_token = blank_id
    time_idx = 0
    symbols_added = 0

    def state_input_for_output(out_name: str) -> Optional[str]:
        if out_name in input_state_names:
            return out_name
        if out_name.startswith("output_"):
            candidate = "input_" + out_name[len("output_") :]
            if candidate in input_state_names:
                return candidate
        if out_name.startswith("output_states_"):
            candidate = "input_states_" + out_name[len("output_states_") :]
            if candidate in input_state_names:
                return candidate
        for candidate in input_state_names:
            if candidate in out_name or out_name in candidate:
                return candidate
        return None

    while time_idx < t_total:
        encoder_frame = encoder_outputs[:, :, time_idx : time_idx + 1].astype(
            np.float32,
            copy=False,
        )
        feed = _build_decoder_inputs(
            decoder_input_names,
            encoder_frame=encoder_frame,
            encoder_frame_idx=time_idx,
            encoded_lengths=t_total,
            last_token=last_token,
            decoder_states=decoder_states,
        )
        outputs = decoder_session.run(decoder_output_names, feed)
        outputs_by_name = dict(zip(decoder_output_names, outputs))
        joint_logits = np.squeeze(np.asarray(outputs_by_name[joint_out]))
        if joint_logits.ndim > 1:
            joint_logits = joint_logits.reshape(-1, joint_logits.shape[-1])[-1]

        token_logits = joint_logits[:-n_dur] if n_dur > 0 else joint_logits
        duration_logits = joint_logits[-n_dur:] if n_dur > 0 else None
        token_id = _softmax_argmax(token_logits)
        step = _softmax_argmax(duration_logits) if duration_logits is not None else (1 if token_id == blank_id else 0)
        step_key = str(step)
        diagnostics.duration_step_counts[step_key] = diagnostics.duration_step_counts.get(step_key, 0) + 1

        if token_id == blank_id:
            diagnostics.blank_steps += 1
            time_idx += max(1, step)
            symbols_added = 0
            continue

        diagnostics.nonblank_steps += 1
        piece = vocab[token_id] if 0 <= token_id < len(vocab) else ""
        tokens.append(
            ParakeetToken(
                text=piece,
                start_sec=time_idx * frame_stride_sec,
                end_sec=(time_idx + max(1, step)) * frame_stride_sec,
            )
        )
        last_token = token_id
        diagnostics.first_emitted_frame = (
            time_idx
            if diagnostics.first_emitted_frame is None
            else diagnostics.first_emitted_frame
        )
        diagnostics.last_emitted_frame = time_idx

        for out_name in state_outs:
            in_name = state_input_for_output(out_name)
            if in_name is not None:
                decoder_states[in_name] = np.asarray(outputs_by_name[out_name])

        if step > 0:
            time_idx += step
            symbols_added = 0
        else:
            symbols_added += 1
            if symbols_added >= MAX_SYMBOLS_PER_STEP:
                time_idx += 1
                symbols_added = 0
                diagnostics.forced_advances += 1

    return tokens, diagnostics
