# Parakeet Hand-Rolled Parity Notes

Basil intentionally keeps Parakeet on a lightweight ONNX Runtime path instead of
bundling `nemo_toolkit`. That is still the right boundary: the model bundle
already contains the encoder, decoder/joint graph, vocabulary, and `nemo128.onnx`
preprocessor, so the task is to match the reference ONNX semantics rather than
pull in the full training/runtime stack.

The hand-rolled frontend now mirrors the relevant `onnx-asr`/NeMo preprocessor
mechanics:

- pre-emphasis runs before framing;
- the waveform is explicitly zero-padded by `n_fft // 2`;
- the 400-sample Hann window is padded to the 512-sample FFT size;
- mel energies use `log(mel + 2**-24)`;
- per-feature normalization uses valid frames, variance denominator `frames - 1`,
  and `sqrt(var) + 1e-5`.

The decoder also follows the upstream TDT loop shape: blank starts the prediction
network, decoder state advances only after non-blank emissions, zero-duration
non-blank emissions can accumulate at the same encoder frame, and the duration
head argmax is the frame step.

The important lesson from the failing `recording_152249.wav` sample is that
frontend parity is necessary but not sufficient to guarantee Whisper-equivalent
coverage. After the frontend matched `nemo128.onnx`, Parakeet still produced a
shorter transcript than local Whisper on that sample, while the known-good and
attenuated known-good samples matched closely. That points away from Basil's
preprocessor approximation as the sole cause and toward a remaining Parakeet
model/decoder-quality limitation for that kind of audio.
