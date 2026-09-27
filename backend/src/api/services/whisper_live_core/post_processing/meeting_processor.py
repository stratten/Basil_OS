"""
Post-processing orchestration for meeting recordings.

Coordinates transcription, diarization, and merging with granular
progress tracking. This is the main entry point for post-processing.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Callable

from .model_loader import DiarizationModelLoader
from .transcription_processor import TranscriptionProcessor
from .diarization_processor import DiarizationProcessor
from .transcript_merger import (
    ProcessingProgress,
    TranscriptMerger,
    get_audio_duration,
    save_transcript_to_file,
    load_transcript_from_file
)

logger = logging.getLogger(__name__)


class MeetingProcessor:
    """
    Post-processes meeting recordings with accurate, granular progress tracking.
    
    This is the main orchestrator that coordinates:
    - Model loading (Whisper, diarization)
    - Audio transcription with progress tracking
    - Speaker diarization with progress tracking
    - Merging transcripts with speaker labels
    
    Progress is tracked per-stage with real-time updates based on actual processing:
    - Loading: Model initialization (fast, typically <5s)
    - Transcription: Chunk-by-chunk audio processing
    - Diarization: Block-by-block speaker identification
    - Merging: Combining results (fast, typically <1s)
    
    Overall progress is calculated as: (sum of stage completions) / number of stages
    """
    
    def __init__(self, meeting_id: str, model_name: str):
        """
        Initialize meeting processor.
        
        Args:
            meeting_id: Meeting UUID
            model_name: Whisper model to use (e.g., "Base", "Large V3")
        """
        self.meeting_id = meeting_id
        self.model_name = model_name
        
        # Get meeting directory
        from api.services.meetings.meeting_recorder import MeetingRecorder
        self.meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        self.audio_path = self.meeting_dir / "audio.wav"
        self.transcript_path = self.meeting_dir / "transcript.json"
        
        # Resume support: a resumed part's audio is 0-based, but its transcript must
        # stay on the logical meeting timeline. Re-transcription/diarization therefore
        # re-applies this offset so improved segments don't collapse back to 0.
        metadata = MeetingRecorder.load_metadata(meeting_id)
        self.timeline_offset_seconds = (
            float(getattr(metadata, "timeline_offset_seconds", 0.0) or 0.0) if metadata else 0.0
        )
        
        # Processing state
        self.audio_duration = 0.0
        
        # Progress tracking
        self.progress = ProcessingProgress(
            stage="initializing",
            stage_progress=0.0,
            current_time=0.0,
            total_time=0.0,
            message="Initializing...",
            eta_seconds=0.0
        )
        
        logger.info(f"Initialized MeetingProcessor for {meeting_id} with model {model_name}")
    
    async def transcribe_only(
        self,
        progress_callback: Callable[[Dict[str, Any]], None]
    ) -> Dict[str, Any]:
        """
        Transcribe the meeting recording only (no speaker diarization).
        
        Args:
            progress_callback: Async function to call with progress updates
            
        Returns:
            Transcript without speaker labels
        """
        try:
            self.progress.active_stages = ("loading", "transcription")

            # Stage 1: Prepare transcription provider
            self.progress.stage = "loading"
            self.progress.stage_progress = 0.0
            self.audio_duration = get_audio_duration(self.audio_path)
            self.progress.total_time = self.audio_duration
            self.progress.message = "Preparing transcription model..."
            logger.info(f"Audio duration: {self.audio_duration:.1f}s")
            await progress_callback(self.progress.to_dict())
            
            # Mark loading as complete
            self.progress.loading_complete = 1.0
            self.progress.stage_progress = 1.0
            self.progress.message = "Transcription model ready"
            await progress_callback(self.progress.to_dict())
            
            # Stage 2: Transcription
            transcription_processor = TranscriptionProcessor(
                self.audio_path,
                self.audio_duration,
                self.model_name
            )
            
            offset = self.timeline_offset_seconds

            async def transcription_progress(stage_progress, current_time, message, eta_seconds, new_segments=None):
                """Wrapper to update progress tracking.

                ``new_segments`` (optional) carries segments completed since the
                previous emit so the client can render the higher-quality
                re-transcription incrementally. The same resume offset applied to
                the final transcript is applied here so partial and final
                timelines agree.
                """
                self.progress.stage = "transcription"
                self.progress.stage_progress = stage_progress
                self.progress.transcription_complete = stage_progress
                self.progress.current_time = current_time
                self.progress.message = message
                self.progress.eta_seconds = eta_seconds
                if new_segments:
                    self.progress.new_segments = [
                        {
                            "start": seg["start"] + offset,
                            "end": seg["end"] + offset,
                            "text": seg["text"].strip(),
                            "speaker": None,
                        }
                        for seg in new_segments
                    ]
                else:
                    self.progress.new_segments = []
                await progress_callback(self.progress.to_dict())
                # Clear after emit so the next progress update without segments
                # does not resend stale partials.
                self.progress.new_segments = []
            
            transcript_segments = await transcription_processor.transcribe_with_selected_model(transcription_progress)
            
            # Create transcript without speaker labels. Re-apply the resume offset so
            # a resumed part's improved transcript stays on the logical timeline.
            offset = self.timeline_offset_seconds
            existing_transcript = None
            if not transcript_segments and self.transcript_path.exists():
                with open(self.transcript_path, "r") as transcript_file:
                    candidate = json.load(transcript_file)
                if candidate.get("segments"):
                    existing_transcript = candidate

            if existing_transcript is not None:
                transcript = existing_transcript
                completion_message = "No speech detected; existing transcript preserved."
            else:
                transcript = {
                    "meeting_id": self.meeting_id,
                    "segments": [
                        {
                            "start": seg["start"] + offset,
                            "end": seg["end"] + offset,
                            "text": seg["text"].strip(),
                            "speaker": None  # No speaker labels yet
                        }
                        for seg in transcript_segments
                    ]
                }

                # Save the newly transcribed or canonical empty transcript.
                await save_transcript_to_file(
                    transcript,
                    self.transcript_path,
                    audio_path=self.audio_path,
                    timeline_offset_seconds=self.timeline_offset_seconds,
                )
                completion_message = (
                    "No speech detected in this audio source."
                    if not transcript_segments
                    else "Transcription complete"
                )
            
            # Mark complete
            self.progress.stage = "complete"
            self.progress.stage_progress = 1.0
            self.progress.transcription_complete = 1.0
            self.progress.message = completion_message
            await progress_callback(self.progress.to_dict())
            
            logger.info(f"Transcription completed: {len(transcript_segments)} segments")
            return transcript
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            self.progress.stage = "error"
            self.progress.message = f"Transcription failed: {str(e)}"
            await progress_callback(self.progress.to_dict())
            raise
    
    async def diarize_only(
        self,
        progress_callback: Callable[[Dict[str, Any]], None]
    ) -> Dict[str, Any]:
        """
        Add speaker diarization to existing transcript.
        
        Args:
            progress_callback: Async function to call with progress updates
            
        Returns:
            Transcript with speaker labels
        """
        try:
            self.progress.active_stages = ("loading", "diarization", "merging")

            # Load existing transcript
            existing_transcript = load_transcript_from_file(self.transcript_path)
            transcript_segments = existing_transcript.get("segments", [])
            
            # DEBUG: Log what we loaded from disk
            logger.info(f"Loaded {len(transcript_segments)} segments from existing transcript")
            for i, seg in enumerate(transcript_segments[:3]):  # Log first 3
                logger.info(
                    f"  Loaded segment {i}: {seg.get('start', 0):.2f}-{seg.get('end', 0):.2f}s "
                    f"text='{seg.get('text', '')}', speaker={seg.get('speaker')}"
                )
            
            # Stage 1: Load diarization model
            self.progress.stage = "loading"
            self.progress.stage_progress = 0.0
            self.progress.message = "Loading diarization model..."
            self.audio_duration = get_audio_duration(self.audio_path)
            self.progress.total_time = self.audio_duration
            await progress_callback(self.progress.to_dict())
            
            diarization_pipeline = await DiarizationModelLoader.load_pipeline()
            
            self.progress.loading_complete = 1.0
            self.progress.stage_progress = 1.0
            self.progress.message = "Model loaded"
            await progress_callback(self.progress.to_dict())
            
            # Stage 2: Diarization
            diarization_processor = DiarizationProcessor(
                self.audio_path,
                self.audio_duration
            )
            
            async def diarization_progress(stage_progress, current_time, message, eta_seconds):
                """Wrapper to update progress tracking."""
                self.progress.stage = "diarization"
                self.progress.stage_progress = stage_progress
                self.progress.diarization_complete = stage_progress
                self.progress.current_time = current_time
                self.progress.message = message
                self.progress.eta_seconds = eta_seconds
                await progress_callback(self.progress.to_dict())
            
            speaker_segments = await diarization_processor.diarize(
                diarization_pipeline,
                diarization_progress
            )
            
            # Diarization runs on this part's 0-based audio, but the loaded transcript
            # segments are on the logical timeline. Re-apply the resume offset so the
            # speaker segments align with the transcript during the merge below.
            offset = self.timeline_offset_seconds
            if offset:
                for seg in speaker_segments:
                    if "start" in seg and seg["start"] is not None:
                        seg["start"] = seg["start"] + offset
                    if "end" in seg and seg["end"] is not None:
                        seg["end"] = seg["end"] + offset
            
            # DEBUG: Log diarization output before merge
            logger.info(f"Got {len(speaker_segments)} speaker segments from diarization")
            for i, seg in enumerate(speaker_segments[:3]):  # Log first 3
                logger.info(
                    f"  Speaker seg {i}: {seg.get('start'):.2f}-{seg.get('end'):.2f}s "
                    f"speaker={seg.get('speaker')}"
            )
            
            # Stage 3: Merge with existing transcript
            self.progress.stage = "merging"
            self.progress.stage_progress = 0.0
            self.progress.message = "Adding speaker labels..."
            await progress_callback(self.progress.to_dict())
            
            final_transcript = TranscriptMerger.merge(
                transcript_segments,
                speaker_segments,
                self.meeting_id
            )
            
            # DEBUG: Log merge output
            logger.info(f"Merged transcript has {len(final_transcript.get('segments', []))} segments")
            for i, seg in enumerate(final_transcript.get('segments', [])[:3]):  # Log first 3  
                logger.info(
                    f"  Merged seg {i}: {seg.get('start', 0):.2f}-{seg.get('end', 0):.2f}s "
                    f"text='{seg.get('text', '')}', speaker={seg.get('speaker')}"
                )
            
            # Save updated transcript
            await save_transcript_to_file(
                final_transcript,
                self.transcript_path,
                audio_path=self.audio_path,
                timeline_offset_seconds=self.timeline_offset_seconds,
            )
            
            # Mark complete
            self.progress.stage = "complete"
            self.progress.stage_progress = 1.0
            self.progress.diarization_complete = 1.0
            self.progress.merging_complete = 1.0
            self.progress.message = "Speaker identification complete"
            await progress_callback(self.progress.to_dict())
            
            logger.info(f"Diarization completed: {len(speaker_segments)} speaker segments")
            return final_transcript
            
        except Exception as e:
            logger.error(f"Diarization failed: {e}", exc_info=True)
            self.progress.stage = "error"
            self.progress.message = f"Diarization failed: {str(e)}"
            await progress_callback(self.progress.to_dict())
            raise
    
    async def process_both(
        self,
        progress_callback: Callable[[Dict[str, Any]], None]
    ) -> Dict[str, Any]:
        """
        Complete post-processing: transcription followed by diarization.
        
        If transcription succeeds but diarization fails, the transcript is still saved.
        
        Args:
            progress_callback: Async function to call with progress updates
            
        Returns:
            Final transcript (with or without speaker labels depending on success)
        """
        transcript = None
        
        try:
            self.progress.active_stages = ("loading", "transcription", "diarization", "merging")

            # Step 1: Transcription (always runs)
            logger.info("Starting full post-processing: transcription + diarization")
            transcript = await self.transcribe_only(progress_callback)
            
            # Step 2: Diarization (only if transcription succeeded)
            try:
                logger.info("Transcription succeeded, starting diarization")
                final_transcript = await self.diarize_only(progress_callback)
                return final_transcript
                
            except Exception as diart_error:
                # Diarization failed, but transcription succeeded
                logger.error(f"Diarization failed, but transcription is available: {diart_error}")
                
                # Send error notification but mark transcription as complete
                self.progress.stage = "complete"
                self.progress.stage_progress = 1.0
                self.progress.message = "Transcription complete. Diarization failed - you can retry it separately."
                await progress_callback(self.progress.to_dict())
                
                # Return transcript without speaker labels
                return transcript
                
        except Exception as e:
            # Transcription failed - nothing to save
            logger.error(f"Post-processing failed at transcription stage: {e}", exc_info=True)
            self.progress.stage = "error"
            self.progress.message = f"Transcription failed: {str(e)}"
            await progress_callback(self.progress.to_dict())
            raise
