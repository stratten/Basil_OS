"""
Meeting recorder for saving audio and transcripts during live transcription.
"""
import wave
import json
import logging
import math
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict

from . import meeting_recording_registry

logger = logging.getLogger(__name__)

@dataclass
class MeetingMetadata:
    """Metadata for a meeting recording."""
    id: str
    name: str
    purpose: Optional[str] = None
    participants: Optional[List[str]] = None
    start_time: str = ""  # ISO format
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    audio_path: Optional[str] = None
    transcript_path: Optional[str] = None
    is_post_processed: bool = False
    analyses: Optional[List[Dict[str, Any]]] = None  # List of analysis metadata entries
    session_id: Optional[str] = None  # Shared id linking mic + system-audio members of one meeting
    audio_source: Optional[str] = None  # Source of this recording (e.g. "Microphone", "Zoom")
    # Resume support: where this recording part begins in the logical meeting timeline,
    # its stable ordering among resumed parts, and the meeting it was resumed from.
    timeline_offset_seconds: float = 0.0
    recording_part_index: int = 0
    resumed_from_meeting_id: Optional[str] = None
    stream_timeline_ranges: Optional[List[Dict[str, float]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class MeetingRecorder:
    """
    Records audio and transcripts for a meeting.
    Saves to ~/.basil/meetings/{meeting_id}/
    """
    
    def __init__(self, meeting_id: str, sample_rate: int = 16000, channels: int = 1, audio_source: Optional[str] = None, session_id: Optional[str] = None,
                 timeline_offset_seconds: float = 0.0, recording_part_index: int = 0, resumed_from_meeting_id: Optional[str] = None):
        """
        Initialize meeting recorder.
        
        Args:
            meeting_id: Unique identifier for the meeting
            sample_rate: Audio sample rate (default 16kHz)
            channels: Number of channels (default 1/mono)
            audio_source: Source of audio (e.g., "Zoom", "Teams", "Microphone")
            session_id: Shared id linking the mic + system-audio members of one logical meeting
            timeline_offset_seconds: Offset (in seconds) of this recording part within the logical meeting timeline (resume)
            recording_part_index: Stable ordering index of this part among resumed parts
            resumed_from_meeting_id: The meeting/member id this recording was resumed from (diagnostics)
        """
        self.meeting_id = meeting_id
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = 2  # 16-bit audio = 2 bytes per sample
        self.audio_source = audio_source  # Track the audio source for attribution
        self.session_id = session_id  # Links sibling recordings (mic + system) into one meeting
        # Resume continuation context (defaults make a normal fresh recording).
        self.timeline_offset_seconds = timeline_offset_seconds
        self.recording_part_index = recording_part_index
        self.resumed_from_meeting_id = resumed_from_meeting_id
        
        if meeting_recording_registry.is_discarded(meeting_id):
            raise PermissionError(f"Meeting {meeting_id} was discarded and cannot record again")

        # Create meeting directory
        self.meeting_dir = Path.home() / ".basil" / "meetings" / meeting_id
        self.meeting_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.audio_path = self.meeting_dir / "audio.wav"
        self.transcript_path = self.meeting_dir / "transcript.json"
        self.metadata_path = self.meeting_dir / "metadata.json"
        
        # State
        self.audio_file: Optional[wave.Wave_write] = None
        # Underlying raw file handle backing audio_file. Held separately so we can
        # flush PCM bytes to disk mid-recording (the wave writer never flushes and
        # only patches its header size on close), making audio.wav readable by a
        # concurrent windowed re-transcriber while recording continues.
        self._raw_audio_handle = None
        self._frames_since_flush = 0
        self.transcript_segments: List[Dict[str, Any]] = []
        self.metadata: Optional[MeetingMetadata] = None
        self.is_recording = False
        self.frames_written = 0
        self._stream_timeline_origin_seconds: Optional[float] = None
        self._stream_start_frame_count: Optional[int] = None
        self._active_stream_timeline_range: Optional[Dict[str, float]] = None
        
        logger.info(f"Initialized MeetingRecorder for {meeting_id} at {self.meeting_dir}, audio_source={audio_source or 'Microphone'}")
    
    def start_recording(self, meeting_name: str, purpose: Optional[str] = None, 
                       participants: Optional[List[str]] = None,
                       resume_existing: bool = False) -> None:
        """
        Start recording audio to file.
        
        Args:
            meeting_name: Name of the meeting
            purpose: Optional meeting purpose
            participants: Optional list of participant names
            resume_existing: When True, a socket for an already-in-progress part
                has re-opened (e.g. after a keepalive drop / auto-reconnect). In
                that case preserve the existing audio + transcript and continue
                appending instead of refusing or truncating the prior content.
        """
        if self.is_recording:
            logger.warning(f"Meeting {self.meeting_id} is already recording")
            return

        # Reconnect/append path. The client reuses the same meeting_id when an
        # in-progress socket drops and auto-reconnects, so existing audio/transcript
        # here is expected continuation - not an accidental id collision. Preserve
        # and append to it. (Resumed *parts* still use a fresh meeting_id and never
        # take this branch.)
        if resume_existing and (self._existing_audio_has_content() or self._existing_transcript_has_content()):
            self._resume_existing_recording(meeting_name)
            return

        # Safety guard: never silently overwrite an existing non-empty recording.
        # A reused meeting_id (e.g. stale client state) must not truncate the prior
        # audio.wav. Resumed recordings always use a fresh meeting_id, so a populated
        # file here always indicates an accidental collision.
        if self._existing_audio_has_content():
            raise FileExistsError(
                f"Refusing to overwrite existing recording for meeting {self.meeting_id}: "
                f"{self.audio_path} already contains audio. A new recording must use a fresh meeting id."
            )

        # Safety guard: refuse to overwrite a meeting that already has a persisted
        # transcript. The audio guard above covers the common case (real audio),
        # but a meeting can carry a real transcript with empty/zero-length audio
        # (e.g. an imported or post-processed entry); reusing that id would clobber
        # the prior meeting's metadata. An empty stub (no audio AND no transcript)
        # is still safe to restart - see test_empty_stub_recording_can_be_restarted.
        if self._existing_transcript_has_content():
            raise FileExistsError(
                f"Refusing to overwrite existing meeting {self.meeting_id}: "
                f"{self.transcript_path} already contains a transcript. A new recording "
                f"must use a fresh meeting id."
            )

        # Create metadata
        self.metadata = MeetingMetadata(
            id=self.meeting_id,
            name=meeting_name,
            purpose=purpose,
            participants=participants or [],
            start_time=datetime.utcnow().isoformat() + "Z",  # Add Z suffix to indicate UTC
            audio_path=str(self.audio_path),
            transcript_path=str(self.transcript_path),
            session_id=self.session_id,
            audio_source=self.audio_source,
            timeline_offset_seconds=self.timeline_offset_seconds,
            recording_part_index=self.recording_part_index,
            resumed_from_meeting_id=self.resumed_from_meeting_id,
            stream_timeline_ranges=[],
        )
        
        # Save initial metadata
        self._save_metadata()
        
        # Open audio file for writing. We open the raw handle ourselves and wrap
        # it with the wave writer so we retain a reference we can flush mid-stream;
        # wave.Wave_write exposes no public flush and only writes correct header
        # sizes on close().
        try:
            self._raw_audio_handle = open(str(self.audio_path), 'wb')
            self.audio_file = wave.open(self._raw_audio_handle, 'wb')
            self.audio_file.setnchannels(self.channels)
            self.audio_file.setsampwidth(self.sample_width)
            self.audio_file.setframerate(self.sample_rate)
            
            self.is_recording = True
            self.frames_written = 0
            self._frames_since_flush = 0
            meeting_recording_registry.register(self.meeting_id, self)
            
            logger.info(f"Started recording meeting {self.meeting_id}: {meeting_name}")
            logger.info(f"Audio file: {self.audio_path}")
            
        except Exception as e:
            logger.error(f"Failed to start recording: {e}", exc_info=True)
            raise

    def set_stream_timeline_origin_seconds(self, origin_seconds: float) -> None:
        """Map the first PCM frame of this socket connection to meeting time."""
        if not math.isfinite(origin_seconds) or origin_seconds < 0.0:
            raise ValueError("stream timeline origin must be a finite non-negative value")

        self._stream_timeline_origin_seconds = origin_seconds
        self._stream_start_frame_count = self.frames_written
        if self.metadata is None:
            return

        ranges = self.metadata.stream_timeline_ranges
        if ranges is None:
            ranges = []
            self.metadata.stream_timeline_ranges = ranges
        active_range = {"start": origin_seconds, "end": origin_seconds}
        ranges.append(active_range)
        self._active_stream_timeline_range = active_range
        self._save_metadata()

    def reanchor_empty_stream_timeline_range(self, origin_seconds: float) -> bool:
        """Move the active range origin to a measured capture time while the range holds no audio, so a capture start delayed after the timing control still lands at the right meeting time."""
        if (
            self._active_stream_timeline_range is None
            or self._stream_start_frame_count is None
            or self.frames_written != self._stream_start_frame_count
            or not math.isfinite(origin_seconds)
            or origin_seconds < 0.0
        ):
            return False
        self._stream_timeline_origin_seconds = origin_seconds
        self._active_stream_timeline_range["start"] = origin_seconds
        self._active_stream_timeline_range["end"] = origin_seconds
        if self.metadata is not None:
            self._save_metadata()
        return True

    def _update_active_stream_timeline_range(self) -> None:
        if self._active_stream_timeline_range is None or self._stream_start_frame_count is None:
            return
        captured_frames = max(0, self.frames_written - self._stream_start_frame_count)
        self._active_stream_timeline_range["end"] = (
            self._stream_timeline_origin_seconds or 0.0
        ) + captured_frames / self.sample_rate

    def _resume_existing_recording(self, meeting_name: str) -> None:
        """
        Continue an in-progress recording after an auto-reconnect: load the prior
        transcript segments and metadata, then re-open audio.wav positioned to
        append. The wave module has no append mode, so we read the existing frames
        and re-lay them into a fresh writer (a one-time cost that preserves all
        prior audio). New audio/segments are then written on top.
        """
        # Preserve prior transcript segments so subsequent saves include them.
        self._load_existing_transcript_segments()

        # Preserve original metadata (start_time, name, timeline offset, etc.).
        # Fall back to a fresh record only if the prior metadata is missing.
        existing_meta = MeetingRecorder.load_metadata(self.meeting_id)
        if existing_meta is not None:
            self.metadata = existing_meta
        else:
            self.metadata = MeetingMetadata(
                id=self.meeting_id,
                name=meeting_name,
                start_time=datetime.utcnow().isoformat() + "Z",
                audio_path=str(self.audio_path),
                transcript_path=str(self.transcript_path),
                session_id=self.session_id,
                audio_source=self.audio_source,
                timeline_offset_seconds=self.timeline_offset_seconds,
                recording_part_index=self.recording_part_index,
                resumed_from_meeting_id=self.resumed_from_meeting_id,
                stream_timeline_ranges=[],
            )
            self._save_metadata()

        # Read the existing audio so we can re-lay it ahead of the appended audio.
        existing_frames = b""
        existing_nframes = 0
        if self.audio_path.exists():
            try:
                with wave.open(str(self.audio_path), 'rb') as existing:
                    existing_nframes = existing.getnframes()
                    existing_frames = existing.readframes(existing_nframes)
            except Exception as e:
                logger.warning(
                    f"Could not read existing audio for append on meeting {self.meeting_id}: {e}; "
                    f"continuing without preserved audio frames."
                )
                existing_frames = b""
                existing_nframes = 0

        try:
            self._raw_audio_handle = open(str(self.audio_path), 'wb')
            self.audio_file = wave.open(self._raw_audio_handle, 'wb')
            self.audio_file.setnchannels(self.channels)
            self.audio_file.setsampwidth(self.sample_width)
            self.audio_file.setframerate(self.sample_rate)
            if existing_frames:
                self.audio_file.writeframes(existing_frames)

            self.is_recording = True
            self.frames_written = existing_nframes
            meeting_recording_registry.register(self.meeting_id, self)
            self._frames_since_flush = 0

            logger.info(
                f"Resumed (append) recording for meeting {self.meeting_id}: "
                f"preserved {existing_nframes} audio frames and "
                f"{len(self.transcript_segments)} transcript segments"
            )
        except Exception as e:
            logger.error(f"Failed to resume recording (append): {e}", exc_info=True)
            raise

    def _load_existing_transcript_segments(self) -> None:
        """Load previously persisted transcript segments into memory so a resumed
        (appended) recording keeps them when it next saves the transcript."""
        if not self.transcript_path.exists():
            return
        try:
            with open(self.transcript_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(
                f"Could not load existing transcript for append on meeting {self.meeting_id}: {e}"
            )
            return
        segments = data.get("segments") if isinstance(data, dict) else None
        if isinstance(segments, list):
            self.transcript_segments = segments

    def write_audio_chunk(self, pcm_data: bytes) -> None:
        """
        Write PCM audio chunk to file.
        
        Args:
            pcm_data: Raw PCM audio data (16-bit signed integer, little-endian)
        """
        if not self.is_recording or self.audio_file is None:
            return
        
        try:
            frames_in_chunk = len(pcm_data) // self.sample_width
            self.audio_file.writeframes(pcm_data)
            self.frames_written += frames_in_chunk
            self._frames_since_flush += frames_in_chunk
            self._update_active_stream_timeline_range()

            # Flush roughly once per second of audio so the bytes reach disk and a
            # concurrent reader (windowed re-transcription) sees the growing file.
            # The wave header's frame count stays stale until close(); the live
            # reader derives the available frame count from file size instead.
            if self._raw_audio_handle is not None and self._frames_since_flush >= self.sample_rate:
                self._raw_audio_handle.flush()
                self._frames_since_flush = 0
            
            # Log every 10 seconds of audio
            duration = self.frames_written / self.sample_rate
            if int(duration) % 10 == 0 and int(duration) > 0:
                logger.debug(f"Recorded {duration:.1f}s of audio for meeting {self.meeting_id}")
                
        except Exception as e:
            logger.error(f"Failed to write audio chunk: {e}", exc_info=True)
    
    def add_transcript_segment(self, start: float, end: float, text: str, 
                              speaker: Optional[str] = None, is_interim: bool = False) -> None:
        """
        Add a transcript segment.
        
        Args:
            start: Start time in seconds
            end: End time in seconds
            text: Transcribed text
            speaker: Optional speaker label (will use audio_source if not provided)
            is_interim: Whether this is an interim result
        """
        # Use audio source as speaker attribution if no speaker provided
        # This handles audio tap recordings where we know the source app
        effective_speaker = speaker if speaker else (self.audio_source if self.audio_source else "Speaker 1")
        
        # Place resumed parts on the logical meeting timeline so reopened/merged
        # transcripts interleave correctly. Offset is 0.0 for fresh recordings.
        offset = self.timeline_offset_seconds
        offset_start = start + offset
        offset_end = end + offset
        
        segment = {
            "start": offset_start,
            "end": offset_end,
            "text": text,
            "speaker": effective_speaker,
            "is_interim": is_interim
        }
        
        # Only keep final segments (remove old interim versions)
        if not is_interim:
            # Remove any interim segments that overlap with this final segment
            # (compare on the same offset timeline the stored segments use)
            self.transcript_segments = [
                s for s in self.transcript_segments 
                if s.get("is_interim", False) == False or s["start"] >= offset_end or s["end"] <= offset_start
            ]
            self.transcript_segments.append(segment)
            
            # Log every 10 segments
            if len(self.transcript_segments) % 10 == 0:
                logger.debug(f"Saved {len(self.transcript_segments)} transcript segments for meeting {self.meeting_id} (source: {effective_speaker})")
    
    def stop_recording(self) -> Optional[Dict[str, Any]]:
        """
        Stop recording and finalize files.
        
        Returns:
            Meeting metadata dictionary, or None if not recording
        """
        if not self.is_recording:
            logger.warning(f"Meeting {self.meeting_id} is not recording")
            return None
        
        try:
            # Close audio file. Closing the wave writer patches the header sizes;
            # then close the underlying raw handle we opened in start_recording.
            if self.audio_file:
                self.audio_file.close()
                self.audio_file = None
            if self._raw_audio_handle is not None:
                try:
                    self._raw_audio_handle.close()
                except Exception:
                    pass
                self._raw_audio_handle = None
            
            # Calculate duration
            duration_seconds = self.frames_written / self.sample_rate
            self._update_active_stream_timeline_range()
            
            # Update metadata
            if self.metadata:
                self.metadata.end_time = datetime.utcnow().isoformat() + "Z"  # Add Z suffix to indicate UTC
                self.metadata.duration_seconds = duration_seconds
                self._save_metadata()
            
            # Save transcript
            self._save_transcript()
            
            self.is_recording = False
            
            meeting_recording_registry.unregister(self.meeting_id, self)
            logger.info(f"Stopped recording meeting {self.meeting_id}")
            logger.info(f"Duration: {duration_seconds:.1f}s, Segments: {len(self.transcript_segments)}")
            logger.info(f"Audio saved to: {self.audio_path}")
            logger.info(f"Transcript saved to: {self.transcript_path}")
            
            return self.metadata.to_dict() if self.metadata else None
            
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}", exc_info=True)
            raise
    
    def abandon_recording(self) -> None:
        """Stop recording without finalizing: close handles and drop in-memory state so nothing is written again."""
        for handle_name in ("audio_file", "_raw_audio_handle"):
            handle = getattr(self, handle_name)
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                pass
            setattr(self, handle_name, None)
        self.is_recording = False
        self.metadata = None
        self.transcript_segments = []
        self._active_stream_timeline_range = None
        meeting_recording_registry.unregister(self.meeting_id, self)
        logger.info(f"Abandoned recording for meeting {self.meeting_id}")

    def _existing_audio_has_content(self) -> bool:
        """
        Return True if an audio.wav already exists for this meeting and contains
        real audio frames. A bare/empty WAV (header only) or missing file returns
        False so brand-new recordings and empty stubs are still allowed.
        """
        if not self.audio_path.exists():
            return False
        try:
            with wave.open(str(self.audio_path), 'rb') as existing:
                return existing.getnframes() > 0
        except Exception:
            # Unreadable/partial file: fall back to size. A valid WAV header is
            # 44 bytes; anything larger likely holds audio we must not destroy.
            try:
                return self.audio_path.stat().st_size > 44
            except Exception:
                return False
    
    def _existing_transcript_has_content(self) -> bool:
        """
        Return True if a transcript.json already exists for this meeting and
        contains at least one segment. A missing or empty/segment-less transcript
        returns False so brand-new recordings and empty stubs remain restartable.
        """
        if not self.transcript_path.exists():
            return False
        try:
            with open(self.transcript_path, 'r') as f:
                data = json.load(f)
        except Exception:
            # Unreadable/partial transcript: treat as content so we never clobber
            # a meeting that has any persisted transcription artifact.
            return True
        segments = data.get("segments") if isinstance(data, dict) else None
        return bool(segments)

    def _save_metadata(self) -> None:
        """Save metadata to JSON file."""
        if not self.metadata:
            return
        
        try:
            with open(self.metadata_path, 'w') as f:
                json.dump(self.metadata.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}", exc_info=True)
    
    def _save_transcript(self) -> None:
        """Save transcript segments to JSON file."""
        try:
            transcript_data = {
                "meeting_id": self.meeting_id,
                "segments": sorted(self.transcript_segments, key=lambda s: s["start"])
            }
            # Windowed re-transcription can finish while recording is active.
            # Replay its durable range replacements over the in-memory streaming
            # transcript so this final raw save never regresses prior upgrades.
            from api.services.whisper_live_core.post_processing.meeting_transcript_upgrade_ledger import (
                apply_recorded_window_upgrades,
            )
            transcript_data = apply_recorded_window_upgrades(self.meeting_dir, transcript_data)

            # Atomic write (never leaves a torn file for a concurrent reader)
            # plus a defensive sanitize pass (drops any interim-flagged
            # segment, clamps to the real audio duration, collapses an
            # exact-duplicate trailing run) so this raw save can never persist
            # a corrupted tail even if an upstream bug produces one.
            from api.services.whisper_live_core.post_processing.atomic_json import (
                write_transcript_atomically,
            )
            write_transcript_atomically(
                transcript_data,
                self.transcript_path,
                audio_path=self.audio_path,
                timeline_offset_seconds=self.timeline_offset_seconds,
                timeline_ranges=self.metadata.stream_timeline_ranges if self.metadata else None,
            )

        except Exception as e:
            logger.error(f"Failed to save transcript: {e}", exc_info=True)
    
    def cleanup(self) -> None:
        """Clean up resources (called on error or disconnect)."""
        if self.is_recording:
            logger.warning(f"Cleaning up interrupted recording for meeting {self.meeting_id}")
            try:
                self.stop_recording()
            except:
                pass
        
        if self.audio_file:
            try:
                self.audio_file.close()
            except:
                pass
            self.audio_file = None
        if self._raw_audio_handle is not None:
            try:
                self._raw_audio_handle.close()
            except Exception:
                pass
            self._raw_audio_handle = None
    
    @staticmethod
    def get_meeting_directory(meeting_id: str) -> Path:
        """Get the directory path for a meeting."""
        return Path.home() / ".basil" / "meetings" / meeting_id
    
    @staticmethod
    def load_metadata(meeting_id: str) -> Optional[MeetingMetadata]:
        """Load metadata for a meeting."""
        metadata_path = MeetingRecorder.get_meeting_directory(meeting_id) / "metadata.json"
        
        if not metadata_path.exists():
            return None
        
        try:
            with open(metadata_path, 'r') as f:
                data = json.load(f)
                return MeetingMetadata(**data)
        except Exception as e:
            logger.error(f"Failed to load metadata for meeting {meeting_id}: {e}")
            return None
    
    @staticmethod
    def load_transcript(meeting_id: str) -> Optional[Dict[str, Any]]:
        """Load transcript for a meeting."""
        transcript_path = MeetingRecorder.get_meeting_directory(meeting_id) / "transcript.json"
        
        if not transcript_path.exists():
            return None
        
        try:
            with open(transcript_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load transcript for meeting {meeting_id}: {e}")
            return None
