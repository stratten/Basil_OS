"""
Speaker diarization processing with progress tracking.

Handles speaker identification using diart's streaming inference
with real-time progress updates.
"""
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable
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


class DiarizationProcessor:
    """
    Processes speaker diarization with granular progress tracking.
    
    Uses diart's streaming inference for online speaker clustering
    with periodic progress updates.
    """
    
    def __init__(self, audio_path: Path, audio_duration: float):
        """
        Initialize diarization processor.
        
        Args:
            audio_path: Path to audio file
            audio_duration: Total audio duration in seconds
        """
        self.audio_path = audio_path
        self.audio_duration = audio_duration
    
    async def diarize(
        self,
        diarization_pipeline: Any,
        progress_callback: Callable[[float, float, str, float], None]
    ) -> List[Dict[str, Any]]:
        """
        Perform speaker diarization using diart's native streaming inference.
        
        This properly handles windowed aggregation and speaker clustering.
        
        Args:
            diarization_pipeline: diart SpeakerDiarization pipeline
            progress_callback: Callback(stage_progress, current_time, message, eta_seconds)
            
        Returns:
            List of speaker segments with timestamps and speaker labels
        """
        from diart.sources import FileAudioSource
        from diart.inference import StreamingInference
        import rx.operators as ops
        
        logger.info("Starting speaker diarization")
        
        loop = asyncio.get_running_loop()
        diarization_start = time()
        
        # Reset pipeline to initialize clustering state
        diarization_pipeline.reset()
        
        # Create file audio source (handles proper chunking)
        config = diarization_pipeline.config
        padding = (0, 0)  # No padding needed for post-processing
        source = FileAudioSource(
            str(self.audio_path),
            config.sample_rate,
            padding,
            config.step
        )
        
        # Track progress through a custom observer
        progress_state = {
            "current_time": 0.0,
            "last_update": 0.0
        }
        
        def update_progress(value):
            """Called for each chunk processed."""
            try:
                logger.info(
                    f"[DIAR_PROGRESS] update_progress called with value type: {type(value)}, "
                    f"len: {len(value) if hasattr(value, '__len__') else 'N/A'}"
                )
                # value is (Annotation, SlidingWindowFeature) tuple
                if value and len(value) == 2:
                    annotation, waveform = value
                    # Update current time based on waveform extent
                    progress_state["current_time"] = waveform.extent.end
                    progress_state["last_update"] = time()
                    logger.info(f"[DIAR_PROGRESS] Updated current_time to {waveform.extent.end}s")
                else:
                    logger.warning(f"[DIAR_PROGRESS] Unexpected value format: {value}")
            except Exception as e:
                logger.error(f"[DIAR_PROGRESS] Error in update_progress: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Async progress updater running in parallel
        async def send_progress_updates():
            """Periodically send progress updates while diarization runs."""
            while progress_state["current_time"] < self.audio_duration:
                current_time = progress_state["current_time"]
                if current_time > 0:
                    stage_progress = min(current_time / self.audio_duration, 1.0)
                    elapsed = time() - diarization_start
                    
                    if elapsed > 0:
                        processing_speed = current_time / elapsed
                        remaining_audio = self.audio_duration - current_time
                        remaining_time = remaining_audio / processing_speed if processing_speed > 0 else 0
                    else:
                        remaining_time = 0
                    
                    message = (
                        f"Identifying speakers: {_format_seconds_with_clock(current_time)} / "
                        f"{_format_seconds_with_clock(self.audio_duration)}"
                    )
                    await progress_callback(stage_progress, current_time, message, remaining_time)
                
                # Update every 0.5 seconds
                await asyncio.sleep(0.5)
        
        # Start progress updater task
        progress_task = asyncio.create_task(send_progress_updates())
        
        # Run streaming inference in executor
        def run_streaming_inference():
            # Create inference without progress bar (we handle progress ourselves)
            inference = StreamingInference(
                diarization_pipeline,
                source,
                batch_size=1,  # Process one chunk at a time for progress tracking
                do_profile=False,
                do_plot=False,
                show_progress=False  # We handle progress ourselves
            )
            
            # Subscribe to stream for progress updates
            inference.stream.pipe(
                ops.do_action(update_progress)
            ).subscribe()
            
            # Run inference and get final annotation
            prediction = inference()
            return prediction
        
        # Run in executor to avoid blocking
        try:
            prediction_annotation = await loop.run_in_executor(
                None,
                run_streaming_inference
            )
        finally:
            # Cancel progress task
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        
        # Convert pyannote Annotation to list of segments
        all_annotations = []
        for turn, _, speaker in prediction_annotation.itertracks(yield_label=True):
            all_annotations.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })
        
        # Analyze and log speaker distribution
        self._log_speaker_statistics(all_annotations)
        
        logger.info(f"Diarization complete: {len(all_annotations)} speaker segments")
        return all_annotations
    
    @staticmethod
    def _log_speaker_statistics(annotations: List[Dict[str, Any]]) -> None:
        """
        Analyze and log speaker distribution statistics.
        
        Args:
            annotations: List of speaker segments
        """
        speaker_stats = {}
        
        for seg in annotations:
            speaker = seg["speaker"]
            duration = seg["end"] - seg["start"]
            
            if speaker not in speaker_stats:
                speaker_stats[speaker] = {
                    "count": 0,
                    "total_duration": 0.0,
                    "segments": []
                }
            
            speaker_stats[speaker]["count"] += 1
            speaker_stats[speaker]["total_duration"] += duration
            speaker_stats[speaker]["segments"].append((seg["start"], seg["end"], duration))
        
        logger.info(f"Detected {len(speaker_stats)} unique speakers:")
        for speaker, stats in sorted(speaker_stats.items()):
            avg_duration = stats["total_duration"] / stats["count"] if stats["count"] > 0 else 0
            logger.info(
                f"  {speaker}: {stats['count']} segments, "
                f"total={stats['total_duration']:.2f}s, avg={avg_duration:.2f}s"
            )
            
            # Show first few segments for this speaker
            for i, (start, end, dur) in enumerate(stats["segments"][:3]):
                logger.info(f"    Segment {i}: {start:.2f}-{end:.2f}s (dur={dur:.2f}s)")

