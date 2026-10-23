"""Greedy TDT decoder for NVIDIA Parakeet (ONNX path).

NVIDIA's TDT (Token-and-Duration Transducer) extends the classic RNNT
prediction/joint architecture with an extra duration head: at every
joint step the network emits a token logit ``[V+1]`` (V vocab tokens +
``<blank>``) AND a duration logit over the model's discrete duration
support set (typically ``[0, 1, 2, 3, 4]`` for v2). Greedy decoding
walks the encoder timeline using both heads:

* If the predicted token is ``<blank>``, advance the time cursor by the
  duration-head argmax, falling back to one frame for a zero-duration blank,
  and keep the previous decoder state.
* Otherwise emit the token, update the prediction-network state with
  the new token, and advance the time cursor by the duration-head argmax
  (which may legitimately be ``0`` -- TDT can emit multiple tokens at
  the same encoder frame).

Why a from-scratch implementation? The reference implementation lives
in NeMo's ``RNNTGreedyDecoder``; pulling in ``nemo_toolkit`` just for
this one loop would add ~1 GB of unrelated PyTorch ML deps, dwarfing
the ~30 MB ONNX Runtime alone we already ship. The loop is small (~120
lines) and the ONNX bundle's decoder_joint session does the actual
neural net work, so reimplementing the loop is straightforward.

The decoder output is a list of :class:`ParakeetToken` triples
``(text, start_sec, end_sec)`` where ``text`` is the SentencePiece
piece (with the leading ``▁`` boundary marker preserved). The caller
(:class:`ParakeetTranscriptionService`) is responsible for joining the
pieces into words.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# FastConformer encoder downsamples the 10 ms-hop mel input by 8x, so each
# encoder frame represents 80 ms of audio. Used to convert frame indices
# to wall-clock timestamps for word-level timing.
DEFAULT_FRAME_STRIDE_SEC: float = 0.08

# Hard cap on consecutive token emissions at the same encoder frame.
# Without it a pathological joint output could loop forever; NeMo uses
# 10 by default.
MAX_SYMBOLS_PER_STEP: int = 10


@dataclass
class ParakeetToken:
    """One detokenized SentencePiece piece with its time alignment.

    The piece keeps its leading ``▁`` marker (NeMo's BPE convention)
    when present so the caller can detect word boundaries by checking
    the prefix.
    """

    text: str
    start_sec: float
    end_sec: float


def _softmax_argmax(logits: np.ndarray) -> int:
    """Greedy argmax over the last axis of a 1-D logit vector."""
    return int(np.argmax(logits))


def _build_decoder_inputs(
    decoder_input_names: Sequence[str],
    encoder_frame: np.ndarray,
    encoder_frame_idx: int,
    encoded_lengths: int,
    last_token: int,
    decoder_states: Dict[str, np.ndarray],
) -> Dict[str, np.ndarray]:
    """Map our internal state into the decoder_joint ONNX input dict.

    Different community re-exports of the bundle use slightly different
    input names; we use string-prefix matching against the cached input
    name list rather than hard-coding so renames do not break us. A
    missing recognized input is logged and left as zero -- the encoder
    + token + state inputs are the ones the model actually needs; any
    extra ones (e.g. an unused ``cache_last_channel``) are typically
    pre-filled by the export.
    """
    feed: Dict[str, np.ndarray] = {}

    for name in decoder_input_names:
        lname = name.lower()
        if "encoder_outputs" in lname or "encoder_output" in lname or lname == "encoder":
            # Some exports expect a single frame [B, 1, D]; others expect
            # the whole encoder tensor [B, T, D] plus an index. We feed a
            # single frame which works for the istupakov bundle.
            feed[name] = encoder_frame
        elif "encoded_lengths" in lname or lname == "encoder_outputs_length":
            feed[name] = np.asarray([encoded_lengths], dtype=np.int64)
        elif lname in ("targets", "target", "decoder_input", "labels"):
            # Prediction network input: previous emitted token. Shape [B, 1].
            feed[name] = np.asarray([[last_token]], dtype=np.int32)
        elif "target_length" in lname or lname in ("target_lengths",):
            feed[name] = np.asarray([1], dtype=np.int32)
        elif "state" in lname or lname.startswith("h_") or lname.startswith("c_"):
            # Decoder LSTM/GRU state tensors, keyed by name in our
            # internal dict so we can persist them across steps.
            if name in decoder_states:
                feed[name] = decoder_states[name]
            else:
                # First call: no state yet. We need shape info to build
                # zero state. The caller (decode_tdt_greedy) seeds these
                # before the first step; if we hit this branch the state
                # is genuinely missing for this export.
                logger.debug(
                    f"Decoder state input '{name}' has no seeded zero "
                    f"tensor; the export may need a custom seed."
                )
        else:
            # Unknown input name -- skip rather than guess. The session
            # will raise if it is genuinely required, surfacing a clear
            # error message we can map back to the export's docs.
            pass

    return feed


def _seed_zero_decoder_states(
    decoder_session: Any,
) -> Dict[str, np.ndarray]:
    """Build zero-initialized state tensors matching the decoder's expected shapes.

    Reads each state-shaped input's declared shape from the session and
    materializes a float32 zero tensor of that shape. Symbolic dim names
    (e.g. ``"batch"``) are resolved to ``1`` since we always run with a
    single utterance.
    """
    states: Dict[str, np.ndarray] = {}
    for inp in decoder_session.get_inputs():
        lname = inp.name.lower()
        if not ("state" in lname or lname.startswith("h_") or lname.startswith("c_")):
            continue
        shape: List[int] = []
        for dim in inp.shape:
            if isinstance(dim, int) and dim > 0:
                shape.append(dim)
            else:
                # Symbolic / dynamic dim -- assume batch.
                shape.append(1)
        states[inp.name] = np.zeros(shape, dtype=np.float32)
    return states


def _classify_decoder_outputs(
    output_names: Sequence[str],
) -> Tuple[Optional[str], List[str]]:
    """Identify which output is the joint-logit tensor and which are the new states.

    Returns ``(joint_output_name, state_output_names)``.

    Important: the istupakov bundle's ``decoder_joint-model.onnx`` for
    Parakeet TDT v2 emits a SINGLE ``outputs`` tensor of length
    ``vocab_size + n_durations`` (1025 + 5 = 1030 for v2), with the
    duration logits concatenated to the tail of the token logits, NOT a
    separate ``durations`` output. This matches the upstream
    ``onnx-asr`` reference implementation
    (``NemoConformerTdt._decode``), which splits the single tensor in
    Python via ``output[:vocab_size]`` / ``output[vocab_size:].argmax()``.

    Earlier versions of this helper looked for a separate output whose
    name contained ``"duration"``; that branch was dead in practice
    (the bundle has no such output) AND it also caused the caller to
    ``argmax`` over the full 1030-wide concatenated tensor when
    selecting the next token, which produced spurious "duration" token
    ids in the 1025-1029 range that fell off the end of the vocab. The
    duration split is now done in :func:`decode_tdt_greedy` after the
    session.run call, where we have the full ``outputs`` array and the
    ``durations`` support set in scope.

    Heuristics for naming:

    * Joint logit name typically contains ``"output"``, ``"logit"``,
      ``"joint"``, or ``"prob"`` (istupakov v2 uses ``"outputs"``).
    * State outputs typically contain ``"state"`` or are
      ``"h_n"`` / ``"c_n"`` (istupakov v2 uses ``"output_states_1"``
      and ``"output_states_2"``).
    """
    joint_name: Optional[str] = None
    state_names: List[str] = []

    for name in output_names:
        lname = name.lower()
        if "state" in lname or lname.startswith("h_") or lname.startswith("c_"):
            state_names.append(name)
        elif joint_name is None and (
            "output" in lname or "logit" in lname or "joint" in lname or "prob" in lname
        ):
            joint_name = name

    if joint_name is None and output_names:
        for name in output_names:
            if name not in state_names:
                joint_name = name
                break

    return joint_name, state_names


def decode_tdt_greedy(
    encoder_outputs: np.ndarray,
    encoded_lengths: np.ndarray,
    decoder_session: Any,
    vocab: Sequence[str],
    blank_id: int,
    *,
    durations: Optional[Sequence[int]] = None,
    frame_stride_sec: float = DEFAULT_FRAME_STRIDE_SEC,
    decoder_input_names: Optional[Sequence[str]] = None,
    decoder_output_names: Optional[Sequence[str]] = None,
) -> List[ParakeetToken]:
    """Greedy TDT decode of a single utterance's encoder outputs.

    Args:
        encoder_outputs: ``np.ndarray`` of shape ``[1, D, T_enc]`` from
            the Parakeet encoder ONNX session -- NeMo-native
            channels-first layout (axis 1 = encoder hidden dim, axis 2
            = encoder time). The istupakov ONNX export of
            ``encoder-model.onnx`` produces this layout natively; the
            upstream ``onnx-asr`` reference implementation transposes
            to ``[B, T, D]`` for its own decoding loop, but we keep the
            native layout here because the matching
            ``decoder_joint-model.onnx`` ALSO expects single-frame
            input as ``[1, D, 1]`` (i.e. channels-first), so consuming
            the encoder output in its native layout lets us slice one
            frame as ``encoder_outputs[:, :, t:t+1]`` with no
            transposes anywhere in the hot loop.
        encoded_lengths: ``np.ndarray`` of shape ``[1]`` (int64) with
            the valid encoder-frame count.
        decoder_session: ``onnxruntime.InferenceSession`` for the
            ``decoder_joint-model.onnx`` graph.
        vocab: List of vocab strings, indexed by token id. The blank
            token may or may not appear in this list; we never emit
            text for ``blank_id``.
        blank_id: Index of the ``<blank>`` token used by the joint head.
        durations: TDT duration head metadata, e.g. ``[0, 1, 2, 3, 4]``.
            The reference ``onnx-asr`` decoder uses the duration argmax
            index as the frame step; here the sequence length only tells
            us how many logits belong to the duration tail.
        frame_stride_sec: Seconds per encoder frame; for FastConformer
            with 8x subsampling on 10 ms hop this is ``0.08``.
        decoder_input_names: Cached input name list from the manager.
            Auto-introspected if not provided.
        decoder_output_names: Cached output name list from the manager.
            Auto-introspected if not provided.

    Returns:
        List of :class:`ParakeetToken` in emission order.
    """
    if encoder_outputs.ndim != 3 or encoder_outputs.shape[0] != 1:
        raise ValueError(
            f"Expected encoder_outputs shape [1, D, T] (NeMo-native "
            f"channels-first), got {encoder_outputs.shape}"
        )

    # Cap t_total at the actual encoder time-axis length even if the
    # bundle's encoded_lengths over-reports (it should not, but the
    # extra guard is cheap and prevents an out-of-bounds slice). The
    # time axis is axis 2 because the layout is [B, D, T].
    t_total = min(int(encoded_lengths[0]), int(encoder_outputs.shape[2]))
    if t_total <= 0:
        return []

    if decoder_input_names is None:
        decoder_input_names = [i.name for i in decoder_session.get_inputs()]
    if decoder_output_names is None:
        decoder_output_names = [o.name for o in decoder_session.get_outputs()]

    joint_out, state_outs = _classify_decoder_outputs(decoder_output_names)
    if joint_out is None:
        raise RuntimeError(
            f"Could not identify joint logits output among "
            f"{decoder_output_names}"
        )

    # TDT split: the joint head emits a single concatenated tensor of
    # shape [..., vocab_size + n_durations]. We slice it after each
    # session.run rather than expecting two separate outputs (see the
    # _classify_decoder_outputs docstring for the rationale). When
    # `durations` is None we treat the whole tensor as token logits and
    # fall back to RNNT step semantics (blank advances, non-blank
    # stays).
    n_dur = len(durations) if durations is not None else 0

    decoder_states: Dict[str, np.ndarray] = _seed_zero_decoder_states(decoder_session)

    # Map output state name -> input state name. Most NeMo exports use
    # the convention output ``state_1_out`` -> input ``state_1`` (or
    # the same name for both). We try both.
    input_state_names = list(decoder_states.keys())

    def _state_input_for_output(out_name: str) -> Optional[str]:
        if out_name in input_state_names:
            return out_name
        # Common NeMo/onnx-asr naming pair:
        #   output_states_1 -> input_states_1
        #   output_states_2 -> input_states_2
        # If we fail to map these, decoder recurrent state never updates
        # and quality collapses into truncated/garbled output.
        if out_name.startswith("output_"):
            candidate = "input_" + out_name[len("output_") :]
            if candidate in input_state_names:
                return candidate
        # Strip common suffixes.
        for suffix in ("_out", "_output", "Output", "_new"):
            if out_name.endswith(suffix):
                stem = out_name[: -len(suffix)]
                if stem in input_state_names:
                    return stem
        # Another common variant: output_states_* <-> input_states_*.
        if out_name.startswith("output_states_"):
            candidate = "input_states_" + out_name[len("output_states_") :]
            if candidate in input_state_names:
                return candidate
        if out_name.startswith("state_"):
            candidate = "input_" + out_name
            if candidate in input_state_names:
                return candidate
        # Substring fallback.
        for cand in input_state_names:
            if cand in out_name or out_name in cand:
                return cand
        return None

    tokens: List[ParakeetToken] = []
    last_token = blank_id  # Prediction network seed.
    time_idx = 0
    symbols_added = 0
    blank_steps = 0
    nonblank_steps = 0
    forced_advances = 0
    first_emitted_frame: Optional[int] = None
    last_emitted_frame: Optional[int] = None
    duration_step_counts: Dict[int, int] = {}

    while time_idx < t_total:
        # Slice ONE encoder frame from the [B, D, T] tensor along the
        # time axis -> shape [1, D, 1], which is exactly what
        # decoder_joint-model.onnx's `encoder_outputs` input expects
        # (axis 1 = encoder hidden dim D, axis 2 = single-frame
        # window). A previous version sliced the wrong axis (treating
        # the layout as [B, T, D]) and produced [1, 1, D], which the
        # decoder rejected with `Got: 1 Expected: 1024` (the encoder
        # hidden dim) at session.run time. See the encoder layout note
        # in this function's docstring.
        encoder_frame = encoder_outputs[:, :, time_idx : time_idx + 1].astype(
            np.float32, copy=False
        )

        feed = _build_decoder_inputs(
            decoder_input_names,
            encoder_frame=encoder_frame,
            encoder_frame_idx=time_idx,
            encoded_lengths=t_total,
            last_token=last_token,
            decoder_states=decoder_states,
        )

        try:
            outputs = decoder_session.run(decoder_output_names, feed)
        except Exception as exc:
            logger.error(
                f"Parakeet decoder ONNX session.run failed at time_idx={time_idx}: "
                f"{exc}"
            )
            raise

        outputs_by_name = dict(zip(decoder_output_names, outputs))
        joint_logits = np.asarray(outputs_by_name[joint_out])
        # Squeeze leading singleton dims so we end up with a 1-D
        # tensor of length [vocab_size + n_durations] (1030 for v2).
        joint_logits = np.squeeze(joint_logits)
        if joint_logits.ndim > 1:
            joint_logits = joint_logits.reshape(-1, joint_logits.shape[-1])[-1]

        # Split the concatenated joint+duration tensor. Without this
        # split, the token argmax would also see the 5 trailing
        # duration logits and could spuriously pick a token id in
        # [vocab_size, vocab_size+n_durations) that maps to nothing in
        # the vocab. With the split, token_logits is exactly the
        # [V+1]-wide vocab+blank slice the upstream onnx-asr reference
        # argmaxes over, and duration_logits is the [n_durations] tail
        # that the TDT duration head emits.
        if n_dur > 0:
            token_logits = joint_logits[:-n_dur]
            duration_logits = joint_logits[-n_dur:]
        else:
            token_logits = joint_logits
            duration_logits = None

        token_id = _softmax_argmax(token_logits)

        if duration_logits is not None:
            duration_idx = _softmax_argmax(duration_logits)
            # Upstream onnx-asr's NemoConformerTdt returns the duration
            # argmax index as the frame step. Do not remap through the
            # YAML support-set values here; doing so would diverge for
            # nonstandard exports even when the output split is correct.
            step = int(duration_idx)
        else:
            # Pure RNNT fallback: blank advances by 1, non-blank stays.
            step = 1 if token_id == blank_id else 0
        duration_step_counts[step] = duration_step_counts.get(step, 0) + 1

        if token_id == blank_id:
            # No token; advance time. Always at least 1 to avoid
            # infinite loops on a degenerate duration prediction.
            blank_steps += 1
            time_idx += max(1, step)
            symbols_added = 0
            continue

        # Emit a token.
        nonblank_steps += 1
        if 0 <= token_id < len(vocab):
            piece = vocab[token_id]
        else:
            piece = ""
        start_sec = time_idx * frame_stride_sec
        end_sec = (time_idx + max(1, step)) * frame_stride_sec
        tokens.append(ParakeetToken(text=piece, start_sec=start_sec, end_sec=end_sec))
        last_token = token_id
        first_emitted_frame = time_idx if first_emitted_frame is None else first_emitted_frame
        last_emitted_frame = time_idx

        # Update the prediction-network state with the new token.
        for out_name in state_outs:
            in_name = _state_input_for_output(out_name)
            if in_name is None:
                continue
            decoder_states[in_name] = np.asarray(outputs_by_name[out_name])

        if step > 0:
            time_idx += step
            symbols_added = 0
        else:
            symbols_added += 1
            if symbols_added >= MAX_SYMBOLS_PER_STEP:
                # Forced advance to avoid an infinite emit loop.
                time_idx += 1
                symbols_added = 0
                forced_advances += 1

    logger.debug(
        "Parakeet TDT decode stats: frames=%s pieces=%s blank_steps=%s nonblank_steps=%s "
        "forced_advances=%s first_emitted_frame=%s last_emitted_frame=%s duration_steps=%s",
        t_total,
        len(tokens),
        blank_steps,
        nonblank_steps,
        forced_advances,
        first_emitted_frame,
        last_emitted_frame,
        duration_step_counts,
    )
    return tokens


def detokenize_pieces(tokens: Sequence[ParakeetToken]) -> str:
    """Join SentencePiece pieces into a normal string.

    The NeMo BPE convention uses ``▁`` (U+2581) as the word-boundary
    marker; we replace it with a leading space and strip the result.
    """
    text = "".join(tok.text for tok in tokens)
    text = text.replace("\u2581", " ").strip()
    return text


def pieces_to_words(
    tokens: Sequence[ParakeetToken],
) -> List[ParakeetToken]:
    """Group BPE pieces into word-level :class:`ParakeetToken` objects.

    Each emitted word inherits the ``start_sec`` of its first piece and
    the ``end_sec`` of its last piece.
    """
    words: List[ParakeetToken] = []
    current_pieces: List[ParakeetToken] = []

    def flush():
        if not current_pieces:
            return
        text = "".join(p.text for p in current_pieces).replace("\u2581", " ").strip()
        if text:
            words.append(
                ParakeetToken(
                    text=text,
                    start_sec=current_pieces[0].start_sec,
                    end_sec=current_pieces[-1].end_sec,
                )
            )
        current_pieces.clear()

    for tok in tokens:
        if tok.text.startswith("\u2581") and current_pieces:
            flush()
        current_pieces.append(tok)
    flush()
    return words
