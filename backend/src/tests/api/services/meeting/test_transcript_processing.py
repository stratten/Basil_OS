"""Tests for the TranscriptProcessor class."""

import unittest
import time
from datetime import datetime
import sys
import os
import pytest

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if project_root not in sys.path:
    sys.path.append(project_root)

# Skip this suite if the meeting service is not present in the current codebase
pytest.importorskip(
    "api.services.meeting.transcript_processing",
    reason="Meeting TranscriptProcessor deprecated or not present in current build",
)
pytest.importorskip(
    "api.services.meeting.meeting_models",
    reason="Meeting models deprecated or not present in current build",
)

from api.services.meeting.transcript_processing import TranscriptProcessor
from api.services.meeting.meeting_models import MeetingTranscriptSegment, AudioSource

class TestTranscriptProcessor(unittest.TestCase):
    """Test cases for the TranscriptProcessor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = TranscriptProcessor({
            "stitch_time_threshold": 2.0,
            "min_segment_confidence": 0.6
        })
        self.meeting_id = "test-meeting-123"
        
    def tearDown(self):
        """Clean up after each test."""
        self.processor.clear_all_caches()
        
    def test_stitch_segments_empty_list(self):
        """Test stitching with an empty list."""
        result = self.processor.stitch_segments(self.meeting_id, [])
        self.assertEqual(result, [])
        
    def test_stitch_segments_single_segment(self):
        """Test stitching with a single segment."""
        segment = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello world",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Hello world")
        
    def test_stitch_segments_same_source_close_in_time(self):
        """Test stitching segments from the same audio source that are close in time."""
        segment1 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        segment2 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user2",  # Different speaker, same source
            text="world",
            start_time=1.5,  # 0.5 seconds after segment1 ends
            end_time=2.0,
            confidence=0.85,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment1, segment2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Hello world")
        self.assertEqual(result[0].start_time, 0.0)
        self.assertEqual(result[0].end_time, 2.0)
        self.assertAlmostEqual(result[0].confidence, 0.875, places=3)  # Average of 0.9 and 0.85
        
    def test_stitch_different_audio_sources(self):
        """Test stitching segments from different audio sources are kept separate."""
        segment1 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        segment2 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",  # Same speaker, different source
            text="world",
            start_time=1.5,
            end_time=2.0,
            confidence=0.85,
            audio_source=AudioSource.SYSTEM_AUDIO  # Different source
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment1, segment2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "Hello")
        self.assertEqual(result[1].text, "world")
        
    def test_stitch_segments_time_threshold(self):
        """Test stitching with segments beyond the time threshold."""
        segment1 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        segment2 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user2",  # Different speaker but same source
            text="world",
            start_time=4.0,  # 3 seconds after segment1 ends (beyond threshold)
            end_time=5.0,
            confidence=0.85,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment1, segment2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "Hello")
        self.assertEqual(result[1].text, "world")
        
    def test_stitch_different_applications(self):
        """Test stitching segments from different applications in system audio."""
        segment1 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.SYSTEM_AUDIO,
            application_name="Zoom"
        )
        
        segment2 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="world",
            start_time=1.5,
            end_time=2.0,
            confidence=0.85,
            audio_source=AudioSource.SYSTEM_AUDIO,
            application_name="Teams"  # Different application
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment1, segment2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "Hello")
        self.assertEqual(result[1].text, "world")
        
    def test_stitch_same_application(self):
        """Test stitching segments from the same application in system audio."""
        segment1 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.SYSTEM_AUDIO,
            application_name="Zoom"
        )
        
        segment2 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user2",  # Different speaker, same app
            text="world",
            start_time=1.5,
            end_time=2.0,
            confidence=0.85,
            audio_source=AudioSource.SYSTEM_AUDIO,
            application_name="Zoom"  # Same application
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment1, segment2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Hello world")
        
    def test_stitch_low_confidence(self):
        """Test stitching with low confidence segments."""
        segment1 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="Hello",
            start_time=0.0,
            end_time=1.0,
            confidence=0.9,
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        segment2 = create_test_segment(
            meeting_id=self.meeting_id,
            speaker_id="user1",
            text="world",
            start_time=1.5,
            end_time=2.0,
            confidence=0.3,  # Low confidence
            audio_source=AudioSource.LOCAL_MICROPHONE
        )
        
        result = self.processor.stitch_segments(self.meeting_id, [segment1, segment2])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "Hello")
        self.assertEqual(result[1].text, "world")
        
    def test_stitch_multiple_segments_by_source(self):
        """Test stitching multiple segments grouped by source."""
        segments = [
            # Local microphone segments
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user1",
                text="Hello",
                start_time=0.0,
                end_time=1.0,
                confidence=0.9,
                audio_source=AudioSource.LOCAL_MICROPHONE
            ),
            # System audio segments
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user2",
                text="I'm on",
                start_time=1.2,
                end_time=1.7,
                confidence=0.88,
                audio_source=AudioSource.SYSTEM_AUDIO,
                application_name="Zoom"
            ),
            # More local mic segments
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user1",
                text="world",
                start_time=1.8,
                end_time=2.3,
                confidence=0.85,
                audio_source=AudioSource.LOCAL_MICROPHONE
            ),
            # More system audio segments
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user2",
                text="a call",
                start_time=2.5,
                end_time=3.0,
                confidence=0.92,
                audio_source=AudioSource.SYSTEM_AUDIO,
                application_name="Zoom"
            ),
        ]
        
        result = self.processor.stitch_segments(self.meeting_id, segments)
        self.assertEqual(len(result), 2)  # 1 segment per source
        
        # Find the mic and system segments
        mic_segment = next((s for s in result if s.audio_source == AudioSource.LOCAL_MICROPHONE), None)
        system_segment = next((s for s in result if s.audio_source == AudioSource.SYSTEM_AUDIO), None)
        
        self.assertIsNotNone(mic_segment)
        self.assertIsNotNone(system_segment)
        
        # Check the text was stitched correctly
        self.assertEqual(mic_segment.text, "Hello world")
        self.assertEqual(system_segment.text, "I'm on a call")
        
    def test_mixed_segments_with_different_timestamps(self):
        """Test stitching with segments from different sources with various timestamps."""
        segments = [
            # First mic segment
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user1",
                text="First mic",
                start_time=0.0,
                end_time=1.0,
                confidence=0.9,
                audio_source=AudioSource.LOCAL_MICROPHONE
            ),
            # First system segment
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user2",
                text="First system",
                start_time=0.5,
                end_time=1.5,
                confidence=0.85,
                audio_source=AudioSource.SYSTEM_AUDIO
            ),
            # Second system segment (should stitch with first system)
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user3",
                text="Second system",
                start_time=2.0,
                end_time=2.5,
                confidence=0.88,
                audio_source=AudioSource.SYSTEM_AUDIO
            ),
            # Second mic segment (should stitch with first mic)
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user4",
                text="Second mic",
                start_time=2.8,
                end_time=3.5,
                confidence=0.92,
                audio_source=AudioSource.LOCAL_MICROPHONE
            ),
            # Third system segment (too far from second - no stitch)
            create_test_segment(
                meeting_id=self.meeting_id,
                speaker_id="user2",
                text="Third system",
                start_time=5.5,
                end_time=6.0,
                confidence=0.95,
                audio_source=AudioSource.SYSTEM_AUDIO
            )
        ]
        
        result = self.processor.stitch_segments(self.meeting_id, segments)
        self.assertEqual(len(result), 3)  # 1 mic segment, 2 system segments
        
        # Check the result is sorted by start_time
        self.assertEqual(result[0].start_time, 0.0)  # First mic
        self.assertEqual(result[1].start_time, 0.5)  # First+Second system
        self.assertEqual(result[2].start_time, 5.5)  # Third system
        
        # Check the stitched text
        self.assertEqual(result[0].text, "First mic Second mic")
        self.assertEqual(result[1].text, "First system Second system")
        self.assertEqual(result[2].text, "Third system")


def create_test_segment(
    meeting_id: str,
    speaker_id: str,
    text: str,
    start_time: float,
    end_time: float,
    confidence: float,
    audio_source: AudioSource,
    application_name: str = None
) -> MeetingTranscriptSegment:
    """Create a test transcript segment."""
    return MeetingTranscriptSegment(
        id=f"segment-{int(time.time() * 1000)}-{speaker_id}",
        meeting_id=meeting_id,
        speaker_id=speaker_id,
        speaker_name=f"Speaker {speaker_id}",
        text=text,
        confidence=confidence,
        start_time=start_time,
        end_time=end_time,
        audio_source=audio_source,
        application_name=application_name
    )


if __name__ == "__main__":
    unittest.main() 