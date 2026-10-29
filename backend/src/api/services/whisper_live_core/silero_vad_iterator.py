import torch
import numpy as np
import warnings
from pathlib import Path

"""
Code is adapted from silero-vad v6: https://github.com/snakers4/silero-vad
"""

def init_jit_model(model_path: str, device=torch.device('cpu')):
    """Load a JIT model from file."""
    model = torch.jit.load(model_path, map_location=device)
    model.eval()
    return model


class OnnxWrapper():
    """ONNX Runtime wrapper for Silero VAD model.

    Inference stays in NumPy and onnxruntime. The live notetaker runs a
    microphone stream and a system-audio stream on worker threads; going
    through libtorch on that path has aborted the process with malloc
    corruption when those calls overlapped.
    """

    def __init__(self, path, force_onnx_cpu=False):
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1

        if force_onnx_cpu and 'CPUExecutionProvider' in onnxruntime.get_available_providers():
            self.session = onnxruntime.InferenceSession(path, providers=['CPUExecutionProvider'], sess_options=opts)
        else:
            self.session = onnxruntime.InferenceSession(path, sess_options=opts)

        self.reset_states()
        if '16k' in path:
            warnings.warn('This model support only 16000 sampling rate!')
            self.sample_rates = [16000]
        else:
            self.sample_rates = [8000, 16000]

    def _as_audio_array(self, x):
        if hasattr(x, "detach"):
            x = x.detach().cpu().numpy()
        x = np.asarray(x, dtype=np.float32)
        if x.ndim == 1:
            x = x[np.newaxis, :]
        if x.ndim > 2:
            raise ValueError(f"Too many dimensions for input audio chunk {x.ndim}")
        return x

    def _validate_input(self, x, sr: int):
        x = self._as_audio_array(x)

        if sr != 16000 and (sr % 16000 == 0):
            step = sr // 16000
            x = x[:, ::step]
            sr = 16000

        if sr not in self.sample_rates:
            raise ValueError(f"Supported sampling rates: {self.sample_rates} (or multiply of 16000)")
        if sr / x.shape[1] > 31.25:
            raise ValueError("Input audio chunk is too short")

        return x, sr

    def reset_states(self, batch_size=1):
        self._state = np.zeros((2, batch_size, 128), dtype=np.float32)
        self._context = np.zeros((0, 0), dtype=np.float32)
        self._last_sr = 0
        self._last_batch_size = 0

    def __call__(self, x, sr: int):

        x, sr = self._validate_input(x, sr)
        num_samples = 512 if sr == 16000 else 256

        if x.shape[-1] != num_samples:
            raise ValueError(f"Provided number of samples is {x.shape[-1]} (Supported values: 256 for 8000 sample rate, 512 for 16000)")

        batch_size = x.shape[0]
        context_size = 64 if sr == 16000 else 32

        if not self._last_batch_size:
            self.reset_states(batch_size)
        if (self._last_sr) and (self._last_sr != sr):
            self.reset_states(batch_size)
        if (self._last_batch_size) and (self._last_batch_size != batch_size):
            self.reset_states(batch_size)

        if self._context.size == 0:
            self._context = np.zeros((batch_size, context_size), dtype=np.float32)

        x = np.concatenate([self._context, x], axis=1)
        if sr in [8000, 16000]:
            ort_inputs = {'input': x, 'state': self._state, 'sr': np.array(sr, dtype='int64')}
            ort_outs = self.session.run(None, ort_inputs)
            out, state = ort_outs
            self._state = np.asarray(state, dtype=np.float32)
        else:
            raise ValueError()

        self._context = x[..., -context_size:]
        self._last_sr = sr
        self._last_batch_size = batch_size

        return np.asarray(out)


def load_silero_vad(model_path: str = None, onnx: bool = True, opset_version: int = 16):
    """
    Load Silero VAD model (ONNX by default, JIT as an explicit opt-in).

    Each call returns a fresh session. Live transcription starts a microphone stream and a system-audio stream; those must not share one model, because Silero keeps hidden state and the JIT path is not safe to call from two threads.

    Parameters
    ----------
    model_path : str, optional
        Path to model file. If None, uses default bundled model.
    onnx : bool, default True
        Whether to use ONNX runtime (requires onnxruntime package). JIT is the historical default and has been observed to abort the process with heap corruption under concurrent live streams.
    opset_version : int, default 16
        ONNX opset version (15 or 16). Only used if onnx=True.
    
    Returns
    -------
    model
        Loaded VAD model (JIT or ONNX wrapper)
    """
    available_ops = [15, 16]
    if onnx and opset_version not in available_ops:
        raise Exception(f'Available ONNX opset_version: {available_ops}')
    if model_path is None:
        current_dir = Path(__file__).parent
        data_dir = current_dir / 'vad_models'
        
        if onnx:
            if opset_version == 16:
                model_name = 'silero_vad.onnx'
            else:
                model_name = f'silero_vad_16k_op{opset_version}.onnx'
        else:
            model_name = 'silero_vad.jit'
        
        model_path = data_dir / model_name
        
        if not model_path.exists():
            raise FileNotFoundError(
                f"Model file not found: {model_path}\n"
                f"Please ensure the whisperlivekit/vad_models/ directory contains the model files."
            )
    else:
        model_path = Path(model_path)
    if onnx:
        try:
            model = OnnxWrapper(str(model_path), force_onnx_cpu=True)
        except ImportError:
            raise ImportError(
                "ONNX runtime not available. Install with: pip install onnxruntime\n"
                "Or use JIT model by setting onnx=False"
            )
    else:
        model = init_jit_model(str(model_path))

    return model


class VADIterator:
    """
    Voice Activity Detection iterator for streaming audio.
    
    This is the Silero VAD v6 implementation.
    """
    
    def __init__(self,
                 model,
                 threshold: float = 0.5,
                 sampling_rate: int = 16000,
                 min_silence_duration_ms: int = 100,
                 speech_pad_ms: int = 30
                 ):

        """
        Class for stream imitation

        Parameters
        ----------
        model: preloaded .jit/.onnx silero VAD model

        threshold: float (default - 0.5)
            Speech threshold. Silero VAD outputs speech probabilities for each audio chunk, probabilities ABOVE this value are considered as SPEECH.
            It is better to tune this parameter for each dataset separately, but "lazy" 0.5 is pretty good for most datasets.

        sampling_rate: int (default - 16000)
            Currently silero VAD models support 8000 and 16000 sample rates

        min_silence_duration_ms: int (default - 100 milliseconds)
            In the end of each speech chunk wait for min_silence_duration_ms before separating it

        speech_pad_ms: int (default - 30 milliseconds)
            Final speech chunks are padded by speech_pad_ms each side
        """

        self.model = model
        self.threshold = threshold
        self.sampling_rate = sampling_rate

        if sampling_rate not in [8000, 16000]:
            raise ValueError('VADIterator does not support sampling rates other than [8000, 16000]')

        self.min_silence_samples = sampling_rate * min_silence_duration_ms / 1000
        self.speech_pad_samples = sampling_rate * speech_pad_ms / 1000
        self.reset_states()

    def reset_states(self):

        self.model.reset_states()
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0

    def __call__(self, x, return_seconds=False, time_resolution: int = 1):
        """
        x: torch.Tensor
            audio chunk (see examples in repo)

        return_seconds: bool (default - False)
            whether return timestamps in seconds (default - samples)

        time_resolution: int (default - 1)
            time resolution of speech coordinates when requested as seconds
        """

        if isinstance(self.model, OnnxWrapper):
            if hasattr(x, "detach"):
                x = x.detach().cpu().numpy()
            x = np.asarray(x, dtype=np.float32)
            window_size_samples = len(x[0]) if x.ndim == 2 else len(x)
            speech_out = self.model(x, self.sampling_rate)
        else:
            if not torch.is_tensor(x):
                try:
                    x = torch.Tensor(x)
                except Exception as error:
                    raise TypeError("Audio cannot be casted to tensor. Cast it manually") from error
            window_size_samples = len(x[0]) if x.dim() == 2 else len(x)
            with torch.no_grad():
                speech_out = self.model(x, self.sampling_rate)

        self.current_sample += window_size_samples
        speech_prob = float(np.asarray(speech_out).item())

        if (speech_prob >= self.threshold) and self.temp_end:
            self.temp_end = 0

        if (speech_prob >= self.threshold) and not self.triggered:
            self.triggered = True
            speech_start = max(0, self.current_sample - self.speech_pad_samples - window_size_samples)
            return {'start': int(speech_start) if not return_seconds else round(speech_start / self.sampling_rate, time_resolution)}

        if (speech_prob < self.threshold - 0.15) and self.triggered:
            if not self.temp_end:
                self.temp_end = self.current_sample
            if self.current_sample - self.temp_end < self.min_silence_samples:
                return None
            else:
                speech_end = self.temp_end + self.speech_pad_samples - window_size_samples
                self.temp_end = 0
                self.triggered = False
                return {'end': int(speech_end) if not return_seconds else round(speech_end / self.sampling_rate, time_resolution)}

        return None


class FixedVADIterator(VADIterator):
    """
    Fixed VAD Iterator that handles variable-length audio chunks, not only exactly 512 frames at once.
    """

    def reset_states(self):
        super().reset_states()
        self.buffer = np.array([], dtype=np.float32)

    def __call__(self, x, return_seconds=False):
        self.buffer = np.append(self.buffer, x)
        ret = None
        while len(self.buffer) >= 512:
            r = super().__call__(self.buffer[:512], return_seconds=return_seconds)
            self.buffer = self.buffer[512:]
            if ret is None:
                ret = r
            elif r is not None:
                if "end" in r:
                    ret["end"] = r["end"]
                if "start" in r and "end" in ret:
                    del ret["end"]
        return ret if ret != {} else None


if __name__ == "__main__":
    model = load_silero_vad(onnx=False)
    vad = FixedVADIterator(model)
    
    audio_buffer = np.array([0] * 512, dtype=np.float32)
    result = vad(audio_buffer)
    print(f"   512 samples: {result}")
    
    # test with 511 samples
    audio_buffer = np.array([0] * 511, dtype=np.float32)
    result = vad(audio_buffer)