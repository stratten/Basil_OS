"""
Transcript merging and shared utilities for post-processing.

Handles merging of transcription segments with speaker diarization labels,
plus common utilities for progress tracking and file I/O.
"""
import wave
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProcessingProgress:
    """Progress information for post-processing with accurate stage tracking."""
    stage: str              # "loading", "transcription", "diarization", "merging", "complete"
    stage_progress: float   # 0.0 to 1.0 (progress within current stage)
    current_time: float     # seconds processed (for transcription/diarization)
    total_time: float       # total audio duration in seconds
    message: str            # Human-readable status
    eta_seconds: float      # Estimated time remaining
    
    # Stage completion tracking (each 0.0 to 1.0)
    loading_complete: float = 0.0
    transcription_complete: float = 0.0
    diarization_complete: float = 0.0
    merging_complete: float = 0.0
    active_stages: Tuple[str, ...] = field(
        default_factory=lambda: ("loading", "transcription", "diarization", "merging")
    )
    # Optional: segments newly completed since the previous progress emit, so the
    # client can render higher-quality re-transcription incrementally. Omitted
    # from the serialized payload when empty (back-compatible).
    new_segments: List[Dict[str, Any]] = field(default_factory=list)
    
    def calculate_overall_progress(self) -> float:
        """
        Calculate overall progress based on actual stage completion.
        Active stages contribute equally so operation-specific progress does not
        reserve space for stages that will not run.
        """
        stage_progress = {
            "loading": self.loading_complete,
            "transcription": self.transcription_complete,
            "diarization": self.diarization_complete,
            "merging": self.merging_complete,
        }
        active_progress = [
            stage_progress[stage]
            for stage in self.active_stages
            if stage in stage_progress
        ]
        if not active_progress:
            return 0.0
        return sum(active_progress) / len(active_progress)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        payload: Dict[str, Any] = {
            "stage": self.stage,
            "stage_progress": self.stage_progress,
            "overall_progress": self.calculate_overall_progress(),
            "current_time": self.current_time,
            "total_time": self.total_time,
            "message": self.message,
            "eta_seconds": self.eta_seconds
        }
        # Only include newly-completed segments when present so existing clients
        # that ignore the field see an unchanged payload shape.
        if self.new_segments:
            payload["new_segments"] = self.new_segments
        return payload


class TranscriptMerger:
    """
    Merges transcription segments with speaker diarization labels.
    
    Uses overlap-based assignment to determine which speaker spoke
    each transcription segment.
    """
    
    @staticmethod
    def merge(
        transcript_segments: List[Dict[str, Any]],
        speaker_segments: List[Dict[str, Any]],
        meeting_id: str
    ) -> Dict[str, Any]:
        """
        Merge transcription segments with speaker labels.
        
        Args:
            transcript_segments: List of transcription segments with timestamps
            speaker_segments: List of speaker segments with timestamps
            meeting_id: Meeting identifier
            
        Returns:
            Merged transcript with speaker labels
        """
        merged_segments = []
        
        for i, trans_seg in enumerate(transcript_segments):
            start = trans_seg["start"]
            end = trans_seg["end"]
            text = trans_seg["text"]
            
            logger.info(f"Merging transcript seg {i}: {start:.2f}-{end:.2f}s, text='{text[:50]}...'")
            
            # Find best matching speaker using overlap
            speaker = TranscriptMerger._find_best_speaker(
                start, end, speaker_segments
            )
            
            # Format speaker label for frontend
            formatted_speaker = TranscriptMerger._format_speaker_label(speaker)
            
            merged_segments.append({
                "start": start,
                "end": end,
                "text": text.strip(),
                "speaker": formatted_speaker if formatted_speaker else "Speaker 1"
            })
        
        # Consolidate consecutive segments from same speaker
        consolidated_segments = TranscriptMerger._consolidate_segments(merged_segments)
        
        return {
            "meeting_id": meeting_id,
            "segments": consolidated_segments
        }
    
    @staticmethod
    def _find_best_speaker(
        start: float,
        end: float,
        speaker_segments: List[Dict[str, Any]]
    ) -> str:
        """
        Find the speaker with maximum overlap for the given time range.
        
        Args:
            start: Segment start time
            end: Segment end time
            speaker_segments: List of speaker segments
            
        Returns:
            Speaker label with maximum overlap
        """
        speaker = None
        max_overlap = 0
        best_match_info = None
        overlap_candidates = []  # Track all overlaps
        
        for spk_seg in speaker_segments:
            spk_start = spk_seg.get("start", 0)
            spk_end = spk_seg.get("end", 0)
            spk_label = spk_seg.get("speaker")
            
            # Calculate overlap
            overlap_start = max(start, spk_start)
            overlap_end = min(end, spk_end)
            overlap = max(0, overlap_end - overlap_start)
            
            # Track significant overlaps (>0.1s)
            if overlap > 0.1:
                overlap_candidates.append({
                    "speaker": spk_label,
                    "overlap": overlap,
                    "spk_duration": spk_end - spk_start,
                    "info": f"{spk_label}:{overlap:.2f}s"
                })
            
            if overlap > max_overlap:
                max_overlap = overlap
                speaker = spk_label
                best_match_info = f"{spk_start:.2f}-{spk_end:.2f}s {spk_label} (overlap={overlap:.2f}s)"
        
        # Log all candidates to see competition
        if len(overlap_candidates) > 1:
            candidates_str = ", ".join([
                c["info"] for c in sorted(overlap_candidates, key=lambda x: -x["overlap"])
            ])
            logger.info(f"  -> Candidates: [{candidates_str}] -> Winner: {speaker}")
        else:
            logger.info(f"  -> Best match: {best_match_info}, assigned speaker={speaker}")
        
        return speaker
    
    @staticmethod
    def _format_speaker_label(speaker: str) -> str:
        """
        Format speaker label for frontend display.
        
        Args:
            speaker: Raw speaker label (e.g., "speaker0", "speaker1")
            
        Returns:
            Formatted label (e.g., "Speaker 1", "Speaker 2")
        """
        if not speaker:
            return None
        
        # Extract number from "speaker0", "speaker1", etc.
        if speaker.startswith("speaker"):
            try:
                speaker_num = int(speaker.replace("speaker", ""))
                return f"Speaker {speaker_num + 1}"  # speaker0 -> Speaker 1
            except ValueError:
                return speaker
        else:
            return speaker
    
    @staticmethod
    def _consolidate_segments(
        segments: List[Dict[str, Any]],
        max_gap: float = 2.0,
        min_duration: float = 1.0,
        max_duration: float = 30.0
    ) -> List[Dict[str, Any]]:
        """
        Consolidate consecutive segments from the same speaker.
        
        Merges nearby segments with the same speaker to create more readable
        conversation chunks instead of word-by-word fragments.
        
        Args:
            segments: Speaker-assigned segments (already sorted by time)
            max_gap: Maximum gap in seconds between segments to merge (default: 2.0s)
            min_duration: Target minimum duration for merged segments (default: 1.0s)
            max_duration: Maximum duration - split if exceeded (default: 30.0s)
            
        Returns:
            Consolidated segments with same speaker merged
        """
        if not segments:
            return []
        
        logger.info(f"Consolidating {len(segments)} segments (max_gap={max_gap}s)")
        
        consolidated = []
        current_group = [segments[0]]
        
        for seg in segments[1:]:
            prev_seg = current_group[-1]
            
            # Check if we should merge with current group
            same_speaker = seg["speaker"] == prev_seg["speaker"]
            gap = seg["start"] - prev_seg["end"]
            within_max_gap = gap <= max_gap
            
            if same_speaker and within_max_gap:
                # Add to current group
                current_group.append(seg)
            else:
                # Finalize current group and start new one
                merged = TranscriptMerger._merge_group(current_group)
                consolidated.append(merged)
                current_group = [seg]
        
        # Don't forget the last group
        if current_group:
            merged = TranscriptMerger._merge_group(current_group)
            consolidated.append(merged)
        
        logger.info(f"Consolidated {len(segments)} segments → {len(consolidated)} merged segments")
        
        # Log first few consolidated segments for verification
        for i, seg in enumerate(consolidated[:3]):
            duration = seg["end"] - seg["start"]
            logger.info(
                f"  Consolidated seg {i}: {seg['start']:.2f}-{seg['end']:.2f}s "
                f"(dur={duration:.2f}s) speaker={seg['speaker']}, "
                f"text='{seg['text'][:60]}...'"
            )
        
        return consolidated
    
    @staticmethod
    def _merge_group(group: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge a group of consecutive segments into one.
        
        Args:
            group: List of segments to merge (same speaker, close in time)
            
        Returns:
            Single merged segment with combined text
        """
        if len(group) == 1:
            return group[0]
        
        # Combine text with spaces, removing extra whitespace
        texts = [seg["text"].strip() for seg in group if seg["text"].strip()]
        merged_text = " ".join(texts)
        
        # Time range: first start → last end
        merged_segment = {
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": merged_text,
            "speaker": group[0]["speaker"]
        }
        
        duration = merged_segment["end"] - merged_segment["start"]
        logger.debug(
            f"Merged {len(group)} segments into one: "
            f"{merged_segment['start']:.2f}-{merged_segment['end']:.2f}s (dur={duration:.2f}s)"
        )
        
        return merged_segment


# Utility functions

def get_audio_duration(audio_path: Path) -> float:
    """
    Get audio file duration in seconds.
    
    Args:
        audio_path: Path to WAV file
        
    Returns:
        Duration in seconds
    """
    try:
        with wave.open(str(audio_path), 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if frames <= 0 or rate <= 0:
                raise ValueError("WAV file contains no usable audio frames")
            duration = frames / float(rate)
        return duration
    except (EOFError, wave.Error, ValueError) as exc:
        raise ValueError(f"Audio file is not a usable WAV recording: {audio_path}") from exc


def validate_audio_file_for_post_processing(audio_path: Path) -> None:
    """Raise a clear error if a meeting audio file cannot be post-processed."""
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    get_audio_duration(audio_path)


async def save_transcript_to_file(
    transcript: Dict[str, Any],
    path: Path,
    audio_path: Path = None,
    timeline_offset_seconds: float = 0.0,
) -> None:
    """
    Save transcript to JSON file asynchronously.

    Uses the same atomic write plus defensive sanitize pass as every other
    transcript.json writer (drops any interim-flagged segment, clamps to the
    real audio duration when ``audio_path`` is given, collapses an
    exact-duplicate trailing run), so a partial write or a corrupted tail can
    never reach disk.

    Args:
        transcript: Transcript data
        path: Output file path
        audio_path: Path to the meeting's audio.wav, used to clamp segments
            to the real recording duration. Defaults to ``path``'s sibling
            ``audio.wav`` when not given.
        timeline_offset_seconds: This recording part's resume offset within
            the logical multi-part meeting timeline. A resumed part's segment
            times already carry this offset, so the duration clamp's valid
            window is ``[timeline_offset_seconds, timeline_offset_seconds +
            audio_duration)`` rather than starting at zero.
    """
    from .atomic_json import write_transcript_atomically

    effective_audio_path = audio_path or (path.parent / "audio.wav")
    loop = asyncio.get_running_loop()

    def save_sync():
        write_transcript_atomically(
            transcript,
            path,
            audio_path=effective_audio_path,
            timeline_offset_seconds=timeline_offset_seconds,
        )
        logger.info(f"Saved final transcript to {path}")

    await loop.run_in_executor(None, save_sync)


def load_transcript_from_file(path: Path) -> Dict[str, Any]:
    """
    Load transcript from JSON file.
    
    Args:
        path: Transcript file path
        
    Returns:
        Transcript data
        
    Raises:
        FileNotFoundError: If transcript file doesn't exist
        ValueError: If transcript is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found: {path}")
    
    with open(path, 'r') as f:
        transcript = json.load(f)
    
    if not transcript.get("segments"):
        raise ValueError("Transcript has no segments")
    
    return transcript


def merge_session_transcripts(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge the transcripts of multiple session members (e.g. microphone +
    system audio) into a single chronological transcript for analysis.

    Each segment's speaker label is set to its source so the model sees a
    clear multi-party conversation. When a meaningful diarization speaker is
    also present, it is appended (e.g. "Microphone - Speaker 1"), so real
    speaker attribution slots in automatically once diarization is reliable.

    Args:
        members: List of member dicts, each
            {"source": str, "segments": List[Dict[str, Any]],
             "start_offset_seconds": float}.
            `source` is the human-readable source label (e.g. "Microphone",
            "Google Chrome Helper"). `start_offset_seconds` (optional, default
            0.0) shifts every segment of that member onto the shared session
            timeline to correct cross-track start skew (e.g. the system tap
            beginning ~1.3s after the microphone). When absent/0 the behavior is
            identical to the previous raw-start sort.

    Returns:
        Merged transcript dict {"segments": [...]} sorted by start time.
    """
    # Speaker values that carry no real attribution and should fall back to
    # source-only labeling.
    placeholder_speakers = {"", "none", "unknown"}

    merged_segments: List[Dict[str, Any]] = []

    for member in members:
        source = member.get("source") or "Unknown Source"
        segments = member.get("segments") or []
        try:
            start_offset = float(member.get("start_offset_seconds") or 0.0)
        except (TypeError, ValueError):
            start_offset = 0.0

        for segment in segments:
            original_speaker = segment.get("speaker")
            normalized = str(original_speaker).strip().lower() if original_speaker is not None else ""

            if normalized and normalized not in placeholder_speakers:
                speaker_label = f"{source} - {original_speaker}"
            else:
                speaker_label = source

            merged_segments.append({
                "start": segment.get("start", 0.0) + start_offset,
                "end": segment.get("end", 0.0) + start_offset,
                "text": (segment.get("text") or "").strip(),
                "speaker": speaker_label,
                "source": source,
            })

    # After applying per-track start offsets, both sources live on the shared
    # session timeline, so a stable sort by start time reproduces the true
    # interleaved conversation order.
    merged_segments.sort(key=lambda seg: seg.get("start", 0.0))

    return {"segments": merged_segments}

