"""
Transcription processing with progress tracking.

Handles audio transcription using Whisper models with support for
multiple backends (faster-whisper and HuggingFace transformers).
"""
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable, Tuple
from time import time

logger = logging.getLogger(__name__)


def _format_elapsed_clock(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_seconds_with_clock(seconds: float) -> str:
    return f"{seconds:.1f}s ({_format_elapsed_clock(seconds)})"


class TranscriptionProcessor:
    """
    Processes audio transcription with granular progress tracking.
    
    Supports two backends:
    - faster-whisper: Streaming inference with real-time progress
    - HuggingFace transformers: Batch processing with better text formatting
    """
    
    def __init__(self, audio_path: Path, audio_duration: float, model_name: str):
        """
        Initialize transcription processor.
        
        Args:
            audio_path: Path to audio file
            audio_duration: Total audio duration in seconds
            model_name: Model name for logging
        """
        self.audio_path = audio_path
        self.audio_duration = audio_duration
        self.model_name = model_name
        self.model_path = None  # Set during transcription

    async def transcribe_with_selected_model(
        self,
        progress_callback: Callable[[float, float, str, float], None]
    ) -> List[Dict[str, Any]]:
        """Transcribe using the registry handler for the selected model."""
        model_id, model_config = self._resolve_model_config()
        handler = model_config.get("handler")
        location = model_config.get("location")

        logger.info(
            f"Resolved post-processing transcription model: "
            f"name={self.model_name}, id={model_id}, handler={handler}, location={location}"
        )

        if location == "cloud":
            return await self._transcribe_api_model(model_id, progress_callback)

        if handler == "parakeet":
            return await self._transcribe_parakeet(model_id, progress_callback)

        whisper_display_name = model_config.get("display_name", self.model_name)
        return await self._transcribe_whisper(whisper_display_name, progress_callback)

    def _resolve_model_config(self) -> Tuple[str, Dict[str, Any]]:
        """Resolve a model id/config from either registry id or display name."""
        from api.core.models.models_registry import (
            get_cloud_transcription_models,
            get_model,
            get_transcription_models,
        )

        direct_config = get_model(self.model_name)
        if direct_config:
            return self.model_name, direct_config

        candidate_registries = (
            get_transcription_models(),
            get_cloud_transcription_models(),
        )
        for registry in candidate_registries:
            for model_id, config in registry.items():
                if config.get("display_name") == self.model_name:
                    return model_id, config

        raise RuntimeError(f"Transcription model is not registered: {self.model_name}")

    async def _transcribe_whisper(
        self,
        model_name: str,
        progress_callback: Callable[[float, float, str, float], None]
    ) -> List[Dict[str, Any]]:
        """Use the existing Whisper local model post-processing path."""
        from .model_loader import WhisperModelLoader

        await progress_callback(
            0.02,
            0.0,
            "Loading Whisper model for re-transcription...",
            0.0,
        )
        whisper_obj, backend, model_path = await WhisperModelLoader.load_model(model_name)
        return await self.transcribe(
            whisper_obj,
            backend,
            model_path,
            progress_callback,
        )

    async def _transcribe_parakeet(
        self,
        model_id: str,
        progress_callback: Callable[[float, float, str, float], None]
    ) -> List[Dict[str, Any]]:
        """Transcribe with Parakeet and convert word timestamps into segments."""
        from .parakeet_chunked_transcriber import ParakeetChunkedTranscriber

        transcriber = ParakeetChunkedTranscriber(
            audio_path=str(self.audio_path),
            audio_duration=self.audio_duration,
            model_id=model_id,
        )
        return await transcriber.transcribe(progress_callback)

    async def _transcribe_api_model(
        self,
        model_id: str,
        progress_callback: Callable[[float, float, str, float], None]
    ) -> List[Dict[str, Any]]:
        """Transcribe with a cloud API model when timestamped output is supported."""
        from api.services.transcription.backends.openai_whisper_api_service import (
            OpenAIWhisperAPITranscriptionService,
        )

        service = OpenAIWhisperAPITranscriptionService(model_id=model_id)
        await progress_callback(
            0.05,
            0.0,
            "Preparing transcript improvement...",
            0.0,
        )
        service.load_model()

        await progress_callback(
            0.20,
            0.0,
            "Preparing meeting audio...",
            0.0,
        )
        async def api_progress(stage_progress, current_time, message, eta_seconds):
            await progress_callback(stage_progress, current_time, message, eta_seconds)

        segments = await service.transcribe_segments_from_file(
            self.audio_path,
            progress_callback=api_progress,
        )
        await progress_callback(
            1.0,
            self.audio_duration,
            f"Transcript improvement complete: {len(segments)} transcript segments",
            0.0,
        )
        return segments

    async def transcribe(
        self,
        model: Any,
        backend: str,
        model_path: Path,
        progress_callback: Callable[[float, float, str], None]
    ) -> List[Dict[str, Any]]:
        """
        Transcribe audio with progress tracking.

        Args:
            model: Loaded Whisper object (HF ASR pipeline or faster-whisper model)
            backend: Backend tag ("huggingface" or "faster_whisper") from the loader
            model_path: Path to model directory (diagnostics/logging)
            progress_callback: Callback(stage_progress, current_time, message)

        Returns:
            List of transcription segments
        """
        self.model_path = model_path
        logger.info(
            f"Starting transcription with model {self.model_name} (backend={backend})"
        )

        if backend == "faster_whisper":
            segments = await self._transcribe_faster_whisper(model, progress_callback)
        else:
            segments = await self._transcribe_huggingface(model, progress_callback)

        logger.info(f"Transcription complete: {len(segments)} segments")
        return segments
    
    async def _transcribe_faster_whisper(
        self,
        model: Any,
        progress_callback: Callable[[float, float, str], None]
    ) -> List[Dict[str, Any]]:
        """
        Transcribe using faster-whisper backend with streaming progress.
        
        Args:
            model: faster-whisper WhisperModel
            progress_callback: Progress update callback
            
        Returns:
            List of transcription segments
        """
        from api.services.transcription.local_model.whisper_decode_params import (
            faster_whisper_kwargs,
        )

        loop = asyncio.get_running_loop()
        transcription_start = time()

        from api.services.transcription.local_model.warm_whisper_pipeline import (
            WarmWhisperPipeline,
        )
        from api.services.transcription.local_model.whisper_source_resolver import (
            resolve_whisper_source,
        )

        source = resolve_whisper_source(self.model_name)

        def build_faster_whisper_model():
            from faster_whisper import WhisperModel

            return WhisperModel(
                str(source.local_dir),
                device="cpu",
                compute_type="float32",
            )

        # Faster-whisper exposes inference as a lazy generator. Keep its lease
        # for the generator lifetime so a cache swap cannot free its model while
        # advancing a segment. HF remains chunk-preemptible above; a later
        # faster-whisper chunk adapter can use the same lease boundary without
        # changing this ownership contract.
        with WarmWhisperPipeline.acquire_inference_lease(
            source.cache_key,
            "faster_whisper",
            "cpu",
            build_faster_whisper_model,
            priority="background",
        ) as leased_model:
            segments_generator, _info = await loop.run_in_executor(
                None,
                lambda: leased_model.transcribe(
                    str(self.audio_path),
                    language="en",
                    beam_size=5,
                    vad_filter=True,
                    **faster_whisper_kwargs(),
                ),
            )

            all_segments = []
            last_end_time = 0.0
            segment_count = 0
            last_emitted_index = 0

            # Process segments as they arrive.
            for segment in segments_generator:
                segment_dict = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                }
                all_segments.append(segment_dict)
                last_end_time = segment.end
                segment_count += 1

                # Update progress every few segments.
                if segment_count % 5 == 0:
                    current_time = last_end_time
                    stage_progress = min(
                        current_time / self.audio_duration, 1.0
                    ) if self.audio_duration > 0 else 0

                    elapsed = time() - transcription_start
                    if elapsed > 0 and current_time > 0:
                        processing_speed = current_time / elapsed
                        remaining_audio = self.audio_duration - current_time
                        remaining_time = remaining_audio / processing_speed if processing_speed > 0 else 0
                    else:
                        remaining_time = 0

                    message = (
                        f"Re-transcribing: {_format_seconds_with_clock(current_time)} / "
                        f"{_format_seconds_with_clock(self.audio_duration)}"
                    )
                    new_segments = all_segments[last_emitted_index:]
                    last_emitted_index = len(all_segments)
                    await progress_callback(stage_progress, current_time, message, remaining_time, new_segments)

        return all_segments
    
    async def _transcribe_huggingface(
        self,
        pipe: Any,
        progress_callback: Callable[[float, float, str], None]
    ) -> List[Dict[str, Any]]:
        """
        Transcribe using a (shared, warm) HuggingFace transformers pipeline with
        incremental progress.

        This provides better text formatting (capitalization, punctuation)
        compared to raw PyTorch Whisper. Processes audio in 30-second chunks
        with progress updates after each chunk. The pipeline is supplied by the
        shared warm cache (loaded once, reused across source files); anti-
        repetition / temperature-fallback decode params are passed per call so
        the shared pipeline's generation_config is never mutated.

        Args:
            pipe: Warm HuggingFace ASR pipeline (from WhisperModelLoader/ModelManager)
            progress_callback: Progress update callback(stage_progress, current_time, message, eta_seconds)

        Returns:
            List of transcription segments
        """
        import soundfile as sf
        from api.services.transcription.local_model.whisper_decode_params import (
            hf_generate_kwargs,
        )

        loop = asyncio.get_running_loop()

        # Load audio first to calculate chunk boundaries
        audio_array, sample_rate = sf.read(str(self.audio_path))
        logger.info(f"Loaded audio: {len(audio_array)} samples at {sample_rate}Hz")

        # Calculate chunk boundaries (30s chunks)
        chunk_duration = 30.0
        chunk_samples = int(chunk_duration * sample_rate)
        total_chunks = (len(audio_array) + chunk_samples - 1) // chunk_samples

        logger.info(f"Will process {total_chunks} chunks of {chunk_duration}s each")

        # Per-call decode params: break runaway repetition and re-decode
        # degenerate/silent segments instead of committing them verbatim.
        generate_kwargs = hf_generate_kwargs()

        # Process chunks one at a time with progress updates
        all_segments = []
        transcription_start = time()

        for chunk_idx in range(total_chunks):
            start_sample = chunk_idx * chunk_samples
            end_sample = min(start_sample + chunk_samples, len(audio_array))
            chunk_audio = audio_array[start_sample:end_sample]
            
            # Calculate timestamps for this chunk
            chunk_start_time = start_sample / sample_rate
            chunk_end_time = end_sample / sample_rate
            
            def process_chunk():
                """Process a single chunk."""
                from api.services.transcription.local_model.model_lifecycle import (
                    ModelManager,
                )

                # A meeting retranscription yields its local Whisper lease after
                # each 30-second audio chunk. Pending live transcription therefore
                # runs before the next background chunk without ever invalidating
                # the pipeline used by this call.
                with ModelManager().acquire_warm_pipeline(
                    self.model_name,
                    priority="background",
                ) as leased_pipe:
                    return leased_pipe(
                        chunk_audio,
                        return_timestamps=True,
                        generate_kwargs=generate_kwargs,
                    )
            
            # Process this chunk
            result = await loop.run_in_executor(None, process_chunk)
            
            # Parse segments from this chunk
            segments_before_chunk = len(all_segments)
            if isinstance(result, dict):
                if "chunks" in result:
                    for sub_chunk in result["chunks"]:
                        # Adjust timestamps relative to overall audio
                        seg = {
                            "start": chunk_start_time + (sub_chunk["timestamp"][0] or 0.0),
                            "end": chunk_start_time + (sub_chunk["timestamp"][1] or chunk_duration),
                            "text": sub_chunk["text"]
                        }
                        all_segments.append(seg)
                elif "text" in result:
                    # Single segment for this chunk
                    seg = {
                        "start": chunk_start_time,
                        "end": chunk_end_time,
                        "text": result["text"]
                    }
                    all_segments.append(seg)
            
            # Calculate and report progress after each chunk
            chunks_completed = chunk_idx + 1
            stage_progress = chunks_completed / total_chunks
            current_time = chunk_end_time
            
            # Calculate ETA
            elapsed = time() - transcription_start
            if elapsed > 0 and chunks_completed > 0:
                avg_time_per_chunk = elapsed / chunks_completed
                remaining_chunks = total_chunks - chunks_completed
                eta_seconds = avg_time_per_chunk * remaining_chunks
            else:
                eta_seconds = 0
            
            message = (
                f"Re-transcribing: {_format_seconds_with_clock(current_time)} / "
                f"{_format_seconds_with_clock(self.audio_duration)}"
            )
            new_segments = all_segments[segments_before_chunk:]
            await progress_callback(stage_progress, current_time, message, eta_seconds, new_segments)
            
            logger.info(
                f"Processed chunk {chunks_completed}/{total_chunks} "
                f"({chunk_start_time:.1f}s-{chunk_end_time:.1f}s) - "
                f"{stage_progress*100:.1f}% complete"
            )
        
        logger.info(f"Parsed {len(all_segments)} total segments from {total_chunks} chunks")
        return all_segments

