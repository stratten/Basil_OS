#!/usr/bin/env python3
"""
Diarization Testing with Synthetic Audio

This script tests speaker diarization accuracy using synthetic audio data.
It creates realistic test scenarios to evaluate the performance of our diarization pipeline.

Usage:
    python test_ami_corpus_diarization.py --list-meetings
    python test_ami_corpus_diarization.py --quick --test
    python test_ami_corpus_diarization.py --meetings test1 test2 --test
"""

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import librosa
import numpy as np
import soundfile as sf

from api.services.whisper_live_core.diarization.diart_backend import DiartDiarization
from api.services.whisper_live_core.timed_objects import SpeakerSegment

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Enable debug logging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('diarization_test')

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "diarization_test_data"


class SimpleDiarization:
    """
    Lightweight synthetic-audio fallback for this test.

    The production diarization path lives in whisper_live_core; this fallback
    only keeps the legacy AMI test runnable when local diart models are absent.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.segments = []
        self.current_speaker = 1
        self.silence_threshold = 0.008
        self.min_silence_duration = 2.0
        self.last_timestamp = 0.0
        self.is_speaking = False
        self.speaking_started = 0.0
        self.use_simple_fallback = True

    async def diarize(self, pcm_array: np.ndarray):
        """Process one synthetic PCM chunk and return accumulated segments."""
        chunk_duration = len(pcm_array) / self.sample_rate
        energy = np.abs(pcm_array).mean() if len(pcm_array) else 0.0
        current_time = self.last_timestamp + chunk_duration

        logger.debug(
            "SimpleDiarization: time=%.2fs, energy=%.4f, threshold=%.4f, speaking=%s",
            current_time,
            energy,
            self.silence_threshold,
            self.is_speaking,
        )

        if energy > self.silence_threshold and not self.is_speaking:
            self.is_speaking = True
            self.speaking_started = self.last_timestamp
        elif energy <= self.silence_threshold and self.is_speaking:
            segment_duration = current_time - self.speaking_started
            if segment_duration > self.min_silence_duration:
                self.segments.append(SpeakerSegment(
                    speaker=f"SPEAKER_{self.current_speaker}",
                    start=self.speaking_started,
                    end=current_time,
                ))
            self.is_speaking = False

        self.last_timestamp = current_time
        return self.segments

    def finalize(self):
        """Finalize any active synthetic speech segment."""
        if self.is_speaking:
            segment_duration = self.last_timestamp - self.speaking_started
            if segment_duration > 0.5:
                self.segments.append(SpeakerSegment(
                    speaker=f"SPEAKER_{self.current_speaker}",
                    start=self.speaking_started,
                    end=self.last_timestamp,
                ))
            self.is_speaking = False
        return self.segments

    def close(self):
        """Mirror the production diarizer close surface."""
        pass


class DiarizationTester:
    """Test diarization using synthetic audio data"""
    
    def __init__(self):
        self.test_data_dir = TEST_DATA_DIR
        self.test_data_dir.mkdir(exist_ok=True)
        
        # Predefined test scenarios
        self.test_scenarios = {
            "test1": {
                "name": "Two Speaker Meeting",
                "speakers": ["Alice", "Bob"],
                "segments": [
                    {"start": 0.0, "end": 5.0, "speaker": "Alice", "freq": 440, "content": "Good morning everyone, let's start today's meeting"},
                    {"start": 5.0, "end": 10.0, "speaker": "Bob", "freq": 523, "content": "Thanks Alice, I'll review the quarterly results"},
                    {"start": 10.0, "end": 15.0, "speaker": "Alice", "freq": 440, "content": "Those numbers look great, what about the new project?"},
                    {"start": 15.0, "end": 20.0, "speaker": "Bob", "freq": 523, "content": "The project is on track, we should finish next month"}
                ]
            },
            "test2": {
                "name": "Three Speaker Conference",
                "speakers": ["Alice", "Bob", "Charlie"],
                "segments": [
                    {"start": 0.0, "end": 4.0, "speaker": "Alice", "freq": 440},
                    {"start": 4.0, "end": 8.0, "speaker": "Bob", "freq": 523},
                    {"start": 8.0, "end": 12.0, "speaker": "Charlie", "freq": 659},
                    {"start": 12.0, "end": 16.0, "speaker": "Alice", "freq": 440},
                    {"start": 16.0, "end": 20.0, "speaker": "Bob", "freq": 523},
                    {"start": 20.0, "end": 24.0, "speaker": "Charlie", "freq": 659}
                ]
            },
            "test3": {
                "name": "Quick Speaker Changes",
                "speakers": ["Speaker1", "Speaker2"],
                "segments": [
                    {"start": 0.0, "end": 2.0, "speaker": "Speaker1", "freq": 440},
                    {"start": 2.0, "end": 4.0, "speaker": "Speaker2", "freq": 523},
                    {"start": 4.0, "end": 6.0, "speaker": "Speaker1", "freq": 440},
                    {"start": 6.0, "end": 8.0, "speaker": "Speaker2", "freq": 523},
                    {"start": 8.0, "end": 10.0, "speaker": "Speaker1", "freq": 440}
                ]
            },
            "test4": {
                "name": "Four Speaker Panel",
                "speakers": ["A", "B", "C", "D"],
                "segments": [
                    {"start": 0.0, "end": 3.0, "speaker": "A", "freq": 440},
                    {"start": 3.0, "end": 6.0, "speaker": "B", "freq": 523},
                    {"start": 6.0, "end": 9.0, "speaker": "C", "freq": 659},
                    {"start": 9.0, "end": 12.0, "speaker": "D", "freq": 784},
                    {"start": 12.0, "end": 15.0, "speaker": "A", "freq": 440}
                ]
            },
            "test5": {
                "name": "Long Single Speaker",
                "speakers": ["Presenter"],
                "segments": [
                    {"start": 0.0, "end": 30.0, "speaker": "Presenter", "freq": 440}
                ]
            }
        }
        
    def list_available_meetings(self) -> List[str]:
        """List available test scenarios"""
        return list(self.test_scenarios.keys())
    
    def create_synthetic_audio(self, scenario_id: str) -> Optional[Tuple[str, Dict]]:
        """Create synthetic test audio based on scenario"""
        try:
            if scenario_id not in self.test_scenarios:
                logger.error(f"Unknown scenario: {scenario_id}")
                return None
                
            scenario = self.test_scenarios[scenario_id]
            logger.info(f"Creating synthetic audio for: {scenario['name']}")
            
            # Calculate total duration
            max_end = max(seg['end'] for seg in scenario['segments'])
            duration = max_end
            sample_rate = 16000
            
            # Create audio array
            audio = np.zeros(int(duration * sample_rate))
            
            # Generate audio for each segment
            for segment in scenario['segments']:
                start_sample = int(segment['start'] * sample_rate)
                end_sample = int(segment['end'] * sample_rate)
                segment_duration = segment['end'] - segment['start']
                
                # Generate time array for this segment
                t = np.linspace(0, segment_duration, end_sample - start_sample)
                
                # Generate tone with some variation to make it more realistic
                base_freq = segment['freq']
                # Add slight frequency modulation
                freq_mod = base_freq + 10 * np.sin(2 * np.pi * 2 * t)
                
                # Generate audio with envelope
                segment_audio = 0.3 * np.sin(2 * np.pi * freq_mod * t)
                
                # Apply envelope to avoid clicks
                envelope_len = min(int(0.1 * sample_rate), len(segment_audio) // 4)
                if envelope_len > 0:
                    # Fade in
                    segment_audio[:envelope_len] *= np.linspace(0, 1, envelope_len)
                    # Fade out
                    segment_audio[-envelope_len:] *= np.linspace(1, 0, envelope_len)
                
                # Add to main audio
                audio[start_sample:end_sample] = segment_audio
            
            # Add realistic background noise
            noise_level = 0.02
            noise = noise_level * np.random.normal(0, 1, len(audio))
            audio = audio + noise
            
            # Normalize
            audio = audio / np.max(np.abs(audio)) * 0.8
            
            # Save audio
            audio_path = self.test_data_dir / f"{scenario_id}_synthetic.wav"
            sf.write(str(audio_path), audio, sample_rate)
            
            # Create ground truth annotations
            annotations = {
                'segments': [
                    {
                        'start': seg['start'],
                        'end': seg['end'],
                        'speaker': seg['speaker'],
                        'content': seg.get('content', '[Synthetic Audio]')
                    }
                    for seg in scenario['segments']
                ],
                'speakers': set(scenario['speakers']),
                'duration': duration,
                'scenario': scenario['name']
            }
            
            # Save annotations
            annotations_path = self.test_data_dir / f"{scenario_id}_annotations.json"
            with open(annotations_path, 'w') as f:
                json.dump(annotations, f, indent=2, default=str)
            
            logger.info(f"Created synthetic audio: {audio_path}")
            logger.info(f"Duration: {duration:.1f}s, Speakers: {len(scenario['speakers'])}, Segments: {len(scenario['segments'])}")
            
            return str(audio_path), annotations
            
        except Exception as e:
            logger.error(f"Error creating synthetic audio: {e}")
            return None
    
    def test_diarization(self, audio_path: str, ground_truth: Dict) -> Dict:
        """Test diarization on a single audio file"""
        try:
            logger.info(f"Testing diarization on {audio_path}...")
            
            # Load audio
            audio, sr = librosa.load(audio_path, sr=16000)
            duration = len(audio) / sr
            
            logger.info(f"Audio duration: {duration:.2f} seconds")
            logger.info(f"Ground truth speakers: {ground_truth['speakers']}")
            logger.info(f"Ground truth segments: {len(ground_truth['segments'])}")
            
            # Initialize diarization
            # Try DiartDiarization first (now that we know it works!)
            try:
                logger.info("Attempting to use DiartDiarization for testing")
                diarizer = DiartDiarization(sample_rate=sr)
                if getattr(diarizer, "use_simple_fallback", False):
                    logger.warning("DiartDiarization fell back to SimpleDiarization")
                else:
                    logger.info("Successfully initialized DiartDiarization with real models!")
            except Exception as e:
                logger.warning(f"Failed to initialize DiartDiarization, using SimpleDiarization: {e}")
                diarizer = SimpleDiarization(sample_rate=sr)
                # Adjust threshold for our synthetic audio
                diarizer.silence_threshold = 0.1  # Lower threshold for synthetic audio
                diarizer.min_silence_duration = 1.0  # Minimum 1 second segments
            
            # Stream audio in real-time chunks like a live meeting
            chunk_size = int(0.1 * sr)  # 100ms chunks (typical real-time streaming)
            predicted_segments = []
            
            logger.info(f"Streaming audio in {len(audio) // chunk_size} chunks of {chunk_size/sr:.1f}s each...")
            
            import time
            import asyncio
            
            # Track segments over time for DiartDiarization
            total_chunks = len(audio) // chunk_size
            
            for i in range(0, len(audio), chunk_size):
                chunk = audio[i:i + chunk_size]
                start_time = i / sr
                chunk_num = i // chunk_size + 1
                
                # Simulate real-time streaming delay (optional, for realism)
                # time.sleep(0.01)  # Uncomment for real-time simulation
                
                try:
                    # Stream audio chunk like live meeting
                    if hasattr(diarizer, 'diarize'):
                        # Use async diarize method for streaming
                        segments = asyncio.run(diarizer.diarize(chunk))
                        
                        # For DiartDiarization, segments accumulate in the observer
                        if hasattr(diarizer, 'observer') and hasattr(diarizer.observer, 'get_segments'):
                            current_segments = diarizer.observer.get_segments()
                            if chunk_num % 50 == 0 or chunk_num == total_chunks:  # Log every 5 seconds or at end
                                logger.debug(f"Time {start_time:.1f}s (chunk {chunk_num}/{total_chunks}): {len(current_segments)} segments detected")
                        
                        # For SimpleDiarization, segments are returned directly
                        elif hasattr(diarizer, 'use_simple_fallback') and diarizer.use_simple_fallback and segments:
                            # SimpleDiarization returns updated segment list each time
                            pass  # We'll collect at the end
                                
                except Exception as e:
                    logger.warning(f"Error processing chunk at {start_time:.1f}s: {e}")
                    continue
            
            # Collect final segments after streaming all audio
            if hasattr(diarizer, 'observer') and hasattr(diarizer.observer, 'get_segments'):
                # DiartDiarization: get accumulated segments from observer
                final_segments = diarizer.observer.get_segments()
                predicted_segments = []
                for segment in final_segments:
                    predicted_segments.append({
                        'start': segment.start,
                        'end': segment.end, 
                        'speaker': segment.speaker
                    })
                logger.info(f"DiartDiarization accumulated segments: {len(predicted_segments)}")
                
            elif hasattr(diarizer, 'finalize'):
                # SimpleDiarization: finalize and get segments
                final_segments = diarizer.finalize()
                for segment in final_segments:
                    predicted_segments.append({
                        'start': segment.start,
                        'end': segment.end,
                        'speaker': segment.speaker
                    })
                logger.info(f"SimpleDiarization finalized segments: {len(predicted_segments)}")
            
            # CRITICAL: Close the diarization to terminate streaming operations
            try:
                if hasattr(diarizer, 'close'):
                    diarizer.close()
                    logger.info("Closed diarization pipeline")
                # Give it a moment to properly shut down
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Error closing diarization: {e}")
            
            logger.info(f"Predicted {len(predicted_segments)} segments after streaming {duration:.1f}s of audio")
            
            # Show detailed segment comparison
            self.print_segment_comparison(ground_truth['segments'], predicted_segments)
            
            # Calculate metrics
            metrics = self.calculate_metrics(ground_truth['segments'], predicted_segments)
            
            return {
                'audio_path': audio_path,
                'scenario': ground_truth.get('scenario', 'Unknown'),
                'duration': duration,
                'ground_truth_segments': len(ground_truth['segments']),
                'ground_truth_speakers': len(ground_truth['speakers']),
                'predicted_segments': len(predicted_segments),
                'predicted_speakers': len(set(seg['speaker'] for seg in predicted_segments if seg['speaker'] != 'unknown')),
                'metrics': metrics,
                'predicted_segments_data': predicted_segments
            }
            
        except Exception as e:
            logger.error(f"Error testing diarization: {e}")
            return {
                'error': str(e),
                'audio_path': audio_path
            }
    
    def calculate_metrics(self, ground_truth: List[Dict], predicted: List[Dict]) -> Dict:
        """Calculate diarization accuracy metrics"""
        try:
            if not ground_truth or not predicted:
                return {
                    'segment_accuracy': 0.0,
                    'speaker_count_accuracy': 0.0,
                    'time_coverage': 0.0,
                    'ground_truth_speakers': len(set(seg['speaker'] for seg in ground_truth)),
                    'predicted_speakers': len(set(seg['speaker'] for seg in predicted if seg['speaker'] != 'unknown'))
                }
            
            # Simple overlap-based metrics
            total_overlap = 0.0
            total_ground_truth_time = 0.0
            
            for gt_seg in ground_truth:
                gt_start, gt_end = gt_seg['start'], gt_seg['end']
                gt_duration = gt_end - gt_start
                total_ground_truth_time += gt_duration
                
                # Find overlapping predicted segments
                best_overlap = 0.0
                for pred_seg in predicted:
                    pred_start, pred_end = pred_seg['start'], pred_seg['end']
                    
                    # Calculate overlap
                    overlap_start = max(gt_start, pred_start)
                    overlap_end = min(gt_end, pred_end)
                    overlap = max(0, overlap_end - overlap_start)
                    
                    best_overlap = max(best_overlap, overlap)
                
                total_overlap += best_overlap
            
            # Calculate accuracy metrics
            segment_accuracy = total_overlap / total_ground_truth_time if total_ground_truth_time > 0 else 0.0
            
            # Speaker count accuracy
            gt_speaker_count = len(set(seg['speaker'] for seg in ground_truth))
            pred_speaker_count = len(set(seg['speaker'] for seg in predicted if seg['speaker'] != 'unknown'))
            speaker_count_accuracy = 1.0 - abs(gt_speaker_count - pred_speaker_count) / max(gt_speaker_count, 1)
            
            return {
                'segment_accuracy': segment_accuracy,
                'speaker_count_accuracy': speaker_count_accuracy,
                'time_coverage': total_overlap / total_ground_truth_time if total_ground_truth_time > 0 else 0.0,
                'ground_truth_speakers': gt_speaker_count,
                'predicted_speakers': pred_speaker_count
            }
            
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return {'error': str(e)}
    
    def print_segment_comparison(self, ground_truth: List[Dict], predicted: List[Dict]):
        """Print detailed segment-by-segment comparison"""
        try:
            print("\n" + "="*80)
            print("REAL-TIME STREAMING DIARIZATION ANALYSIS")
            print("="*80)
            
            print("\n📋 GROUND TRUTH SEGMENTS:")
            for i, gt_seg in enumerate(ground_truth, 1):
                speaker = gt_seg['speaker']
                start, end = gt_seg['start'], gt_seg['end']
                content = gt_seg.get('content', '[Synthetic Audio]')
                print(f"  {i:2d}. {start:5.1f}s - {end:5.1f}s | {speaker:10s} | {content}")
            
            print(f"\n🤖 PREDICTED SEGMENTS ({len(predicted)} total):")
            print("    ℹ️  Many segments expected in real-time streaming - this enables minimal lag!")
            if not predicted:
                print("     No segments detected")
            else:
                # Sort predicted segments by start time
                sorted_predicted = sorted(predicted, key=lambda x: x['start'])
                for i, pred_seg in enumerate(sorted_predicted, 1):
                    speaker = pred_seg['speaker']
                    start, end = pred_seg['start'], pred_seg['end']
                    duration = end - start
                    print(f"  {i:2d}. {start:5.1f}s - {end:5.1f}s | {speaker:10s} | [{duration:.1f}s duration]")
                    
                    # Show if there's a reasonable match with ground truth
                    best_match = self.find_best_overlap(pred_seg, ground_truth)
                    if best_match:
                        overlap_pct = best_match['overlap_percentage']
                        gt_speaker = best_match['gt_segment']['speaker']
                        if overlap_pct > 30:  # Reasonable overlap
                            match_indicator = "✅" if speaker == gt_speaker else "❌"
                            print(f"      → {match_indicator} {overlap_pct:.0f}% overlap with {gt_speaker}")
                        
            print("\n🎯 SPEAKER ATTRIBUTION ACCURACY ANALYSIS:")
            print("    (This shows how well words would be attributed to speakers in real-time)")
            
            # Create time-based analysis for streaming perspective
            total_duration = max(seg['end'] for seg in ground_truth)
            time_step = 0.5  # Analyze every 0.5 seconds
            correct_attributions = 0
            total_attributions = 0
            speaker_consistency_score = 0.0
            
            print(f"\n📊 TIME-BASED ATTRIBUTION ANALYSIS (every {time_step}s):")
            for t in np.arange(0, total_duration, time_step):
                # Find ground truth speaker at this time
                gt_speaker = None
                for gt_seg in ground_truth:
                    if gt_seg['start'] <= t < gt_seg['end']:
                        gt_speaker = gt_seg['speaker']
                        break
                
                if gt_speaker is None:
                    continue  # No speech at this time
                
                # Find predicted speaker at this time
                pred_speakers = []
                for pred_seg in predicted:
                    if pred_seg['start'] <= t < pred_seg['end']:
                        pred_speakers.append(pred_seg['speaker'])
                
                total_attributions += 1
                
                if pred_speakers:
                    # Use majority vote if multiple predictions
                    most_common_pred = max(set(pred_speakers), key=pred_speakers.count)
                    
                    # Map speaker names to consistent numbering
                    gt_speaker_num = self.map_speaker_to_number(gt_speaker)
                    pred_speaker_num = self.map_speaker_to_number(most_common_pred)
                    
                    if gt_speaker_num == pred_speaker_num:
                        correct_attributions += 1
                        attribution_status = "✅"
                    else:
                        attribution_status = "❌"
                    
                    if t % 2.0 < time_step:  # Log every 2 seconds to avoid spam
                        print(f"    T={t:4.1f}s: GT={gt_speaker:8s} → PRED={most_common_pred:8s} {attribution_status}")
                else:
                    print(f"    T={t:4.1f}s: GT={gt_speaker:8s} → PRED=No Detection ❌")
            
            # Calculate streaming attribution accuracy
            if total_attributions > 0:
                attribution_accuracy = (correct_attributions / total_attributions) * 100
                print(f"\n🎯 STREAMING ATTRIBUTION ACCURACY: {attribution_accuracy:.1f}%")
                print(f"    ({correct_attributions}/{total_attributions} time points correctly attributed)")
            
            # Analyze speaker consistency (do consecutive segments from same speaker get same ID?)
            print(f"\n🔄 SPEAKER CONSISTENCY ANALYSIS:")
            consistency_score = self.analyze_speaker_consistency(ground_truth, predicted)
            print(f"    Speaker Identity Consistency: {consistency_score:.1f}%")
            
            # Analyze coverage (how much of each ground truth segment is covered?)
            print(f"\n📈 COVERAGE ANALYSIS:")
            for i, gt_seg in enumerate(ground_truth, 1):
                coverage = self.calculate_segment_coverage(gt_seg, predicted)
                gt_speaker = gt_seg['speaker']
                gt_content = gt_seg.get('content', '[Synthetic]')
                print(f"    GT {i} ({gt_speaker}): {coverage:.1f}% time coverage | {gt_content[:50]}...")
            
            # Real-time streaming verdict
            print(f"\n💡 REAL-TIME STREAMING VERDICT:")
            if attribution_accuracy >= 80:
                print(f"    🟢 EXCELLENT: {attribution_accuracy:.1f}% attribution accuracy is great for real-time!")
                print(f"       Words would appear with correct speakers in live transcription.")
            elif attribution_accuracy >= 60:
                print(f"    🟡 GOOD: {attribution_accuracy:.1f}% attribution accuracy is acceptable for real-time.")
                print(f"       Most words would be correctly attributed, some speaker confusion.")
            else:
                print(f"    🔴 NEEDS WORK: {attribution_accuracy:.1f}% attribution accuracy is too low.")
                print(f"       Significant speaker confusion would occur in live transcription.")
            
            if consistency_score >= 80:
                print(f"    🟢 Speaker identity mapping is consistent ({consistency_score:.1f}%)")
            else:
                print(f"    🟡 Speaker identity mapping could be more consistent ({consistency_score:.1f}%)")
                
            print("="*80)
            
        except Exception as e:
            logger.error(f"Error in segment comparison: {e}")
    
    def map_speaker_to_number(self, speaker_name: str) -> int:
        """Map speaker names to consistent numbers for comparison"""
        # Extract number from speaker name or map known names
        if isinstance(speaker_name, str):
            # Handle various speaker name formats
            if speaker_name == "Alice":
                return 1
            elif speaker_name == "Bob":
                return 2
            elif speaker_name == "Charlie":
                return 3
            elif "speaker0" in speaker_name.lower():
                return 1
            elif "speaker1" in speaker_name.lower():
                return 2
            elif "speaker2" in speaker_name.lower():
                return 3
            else:
                # Try to extract number
                num = extract_number(speaker_name)
                return num if num is not None else 1
        return int(speaker_name) if isinstance(speaker_name, (int, float)) else 1
    
    def analyze_speaker_consistency(self, ground_truth: List[Dict], predicted: List[Dict]) -> float:
        """Analyze how consistently the same speaker gets the same ID throughout"""
        if not predicted:
            return 0.0
        
        # Build speaker mapping from overlaps
        speaker_mappings = {}  # gt_speaker -> [list of predicted speakers that overlap]
        
        for gt_seg in ground_truth:
            gt_speaker = gt_seg['speaker']
            if gt_speaker not in speaker_mappings:
                speaker_mappings[gt_speaker] = []
            
            # Find all predicted segments that overlap with this GT segment
            for pred_seg in predicted:
                if not (pred_seg['end'] <= gt_seg['start'] or pred_seg['start'] >= gt_seg['end']):
                    # There's overlap
                    speaker_mappings[gt_speaker].append(pred_seg['speaker'])
        
        # Calculate consistency for each GT speaker
        consistency_scores = []
        for gt_speaker, pred_speakers in speaker_mappings.items():
            if pred_speakers:
                # Find most common predicted speaker for this GT speaker
                most_common = max(set(pred_speakers), key=pred_speakers.count)
                consistency = pred_speakers.count(most_common) / len(pred_speakers)
                consistency_scores.append(consistency * 100)
        
        return np.mean(consistency_scores) if consistency_scores else 0.0
    
    def calculate_segment_coverage(self, gt_segment: Dict, predicted: List[Dict]) -> float:
        """Calculate what percentage of a ground truth segment is covered by predictions"""
        gt_start, gt_end = gt_segment['start'], gt_segment['end']
        gt_duration = gt_end - gt_start
        
        if gt_duration <= 0:
            return 0.0
        
        # Find all predicted segments that overlap
        covered_time = 0.0
        covered_intervals = []
        
        for pred_seg in predicted:
            pred_start, pred_end = pred_seg['start'], pred_seg['end']
            
            # Calculate overlap
            overlap_start = max(gt_start, pred_start)
            overlap_end = min(gt_end, pred_end)
            
            if overlap_end > overlap_start:
                covered_intervals.append((overlap_start, overlap_end))
        
        # Merge overlapping intervals to avoid double-counting
        if covered_intervals:
            covered_intervals.sort()
            merged_intervals = [covered_intervals[0]]
            
            for start, end in covered_intervals[1:]:
                last_start, last_end = merged_intervals[-1]
                if start <= last_end:
                    # Overlapping, merge
                    merged_intervals[-1] = (last_start, max(last_end, end))
                else:
                    # Non-overlapping, add new interval
                    merged_intervals.append((start, end))
            
            # Calculate total covered time
            covered_time = sum(end - start for start, end in merged_intervals)
        
        return (covered_time / gt_duration) * 100
    
    def find_best_overlap(self, pred_segment: Dict, ground_truth: List[Dict]) -> Optional[Dict]:
        """Find the ground truth segment with best overlap for a predicted segment"""
        best_overlap = 0.0
        best_match = None
        
        pred_start, pred_end = pred_segment['start'], pred_segment['end']
        pred_duration = pred_end - pred_start
        
        for gt_seg in ground_truth:
            gt_start, gt_end = gt_seg['start'], gt_seg['end']
            
            # Calculate overlap
            overlap_start = max(pred_start, gt_start)
            overlap_end = min(pred_end, gt_end)
            
            if overlap_end > overlap_start:
                overlap_duration = overlap_end - overlap_start
                overlap_percentage = (overlap_duration / pred_duration) * 100
                
                if overlap_percentage > best_overlap:
                    best_overlap = overlap_percentage
                    best_match = {
                        'gt_segment': gt_seg,
                        'overlap_percentage': overlap_percentage,
                        'overlap_duration': overlap_duration
                    }
        
        return best_match

    def test_real_ami_corpus_diarization(self, meeting_id: str = "ES2002a"):
        """Test diarization with real AMI Corpus meeting audio"""
        try:
            print(f"\n🎤 TESTING REAL AMI CORPUS MEETING: {meeting_id}")
            print("="*80)
            
            # Try to load AMI corpus from Hugging Face
            try:
                from datasets import load_dataset
                print("📥 Loading AMI Corpus from Hugging Face...")
                
                # Load the updated AMI dataset
                dataset = load_dataset("edinburghcstr/ami", "headset-single", split="validation")
                
                # Find the specific meeting
                meeting_data = None
                for sample in dataset:
                    if meeting_id in sample.get('meeting_id', ''):
                        meeting_data = sample
                        break
                
                if not meeting_data:
                    print(f"❌ Meeting {meeting_id} not found in dataset")
                    return None
                    
                print(f"✅ Found meeting: {meeting_id}")
                print(f"   Duration: {len(meeting_data['audio']['array']) / meeting_data['audio']['sampling_rate']:.1f}s")
                print(f"   Sample rate: {meeting_data['audio']['sampling_rate']}Hz")
                
                # Extract audio and ground truth
                audio_array = meeting_data['audio']['array']
                sample_rate = meeting_data['audio']['sampling_rate']
                
                # Create ground truth from AMI annotations
                ground_truth_segments = []
                if 'words' in meeting_data and 'word_speakers' in meeting_data:
                    # Group consecutive words by speaker
                    current_speaker = None
                    segment_start = None
                    
                    for i, (word, speaker, start_time, end_time) in enumerate(zip(
                        meeting_data['words'],
                        meeting_data['word_speakers'], 
                        meeting_data['word_start_times'],
                        meeting_data['word_end_times']
                    )):
                        if speaker != current_speaker:
                            # End previous segment
                            if current_speaker is not None:
                                ground_truth_segments.append({
                                    'start': segment_start,
                                    'end': start_time,
                                    'speaker': current_speaker,
                                    'content': f"Real speech from speaker {current_speaker}"
                                })
                            
                            # Start new segment
                            current_speaker = speaker
                            segment_start = start_time
                    
                    # Add final segment
                    if current_speaker is not None:
                        ground_truth_segments.append({
                            'start': segment_start,
                            'end': meeting_data['word_end_times'][-1],
                            'speaker': current_speaker,
                            'content': f"Real speech from speaker {current_speaker}"
                        })
                
                # Limit to first 30 seconds for testing
                max_duration = 30.0
                audio_array = audio_array[:int(max_duration * sample_rate)]
                ground_truth_segments = [
                    seg for seg in ground_truth_segments 
                    if seg['start'] < max_duration
                ]
                
                # Adjust end times
                for seg in ground_truth_segments:
                    seg['end'] = min(seg['end'], max_duration)
                
                print(f"📊 Ground truth: {len(ground_truth_segments)} segments from {len(set(seg['speaker'] for seg in ground_truth_segments))} speakers")
                
                # Save audio for streaming test
                audio_file = self.test_data_dir / f"real_ami_{meeting_id}.wav"
                sf.write(audio_file, audio_array, sample_rate)
                
                # Test with streaming diarization
                annotations = {
                    'segments': ground_truth_segments,
                    'speakers': list(set(seg['speaker'] for seg in ground_truth_segments))
                }
                
                result = self.test_streaming_diarization(audio_file, annotations, f"Real AMI {meeting_id}")
                
                # Clean up
                if audio_file.exists():
                    audio_file.unlink()
                    
                return result
                
            except ImportError:
                print("❌ 'datasets' library not available. Install with: pip install datasets")
                return None
            except Exception as e:
                print(f"❌ Error loading AMI dataset: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error in real AMI corpus test: {e}")
            return None

def main():
    parser = argparse.ArgumentParser(description="Test diarization using synthetic audio")
    parser.add_argument('--list-meetings', action='store_true', help='List available test scenarios')
    parser.add_argument('--quick', action='store_true', help='Quick test with one scenario')
    parser.add_argument('--meetings', nargs='+', help='Specific scenarios to test')
    parser.add_argument('--test', action='store_true', help='Run diarization tests')
    parser.add_argument('--all', action='store_true', help='Test all scenarios')
    
    args = parser.parse_args()
    
    tester = DiarizationTester()
    
    if args.list_meetings:
        scenarios = tester.list_available_meetings()
        print("Available test scenarios:")
        for i, scenario_id in enumerate(scenarios, 1):
            scenario = tester.test_scenarios[scenario_id]
            print(f"  {i:2d}. {scenario_id}: {scenario['name']} ({len(scenario['speakers'])} speakers)")
        return
    
    # Determine which scenarios to process
    if args.quick:
        scenarios = ["test1"]  # Single scenario for quick testing
    elif args.all:
        scenarios = tester.list_available_meetings()
    elif args.meetings:
        scenarios = args.meetings
    else:
        scenarios = ["test1", "test2"]  # Default test set
    
    results = []
    
    for scenario_id in scenarios:
        logger.info(f"Processing scenario: {scenario_id}")
        
        # Create synthetic audio
        result = tester.create_synthetic_audio(scenario_id)
        if not result:
            logger.error(f"Failed to create audio for {scenario_id}")
            continue
            
        audio_path, annotations = result
        
        if args.test:
            # Run diarization test
            test_result = tester.test_diarization(audio_path, annotations)
            test_result['scenario_id'] = scenario_id
            results.append(test_result)
    
    if results:
        # Save results
        results_path = TEST_DATA_DIR / "diarization_test_results.json"
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Test results saved to: {results_path}")
        
        # Print summary
        print("\n" + "="*70)
        print("DIARIZATION TEST RESULTS SUMMARY")
        print("="*70)
        
        for result in results:
            if 'error' in result:
                print(f"\n❌ {result.get('scenario_id', 'Unknown')}: ERROR - {result['error']}")
                continue
                
            scenario_id = result.get('scenario_id', 'Unknown')
            scenario_name = result.get('scenario', 'Unknown')
            metrics = result.get('metrics', {})
            
            print(f"\n📊 Scenario: {scenario_id} - {scenario_name}")
            print(f"   Duration: {result.get('duration', 0):.1f}s")
            print(f"   Ground Truth: {result.get('ground_truth_segments', 0)} segments, {result.get('ground_truth_speakers', 0)} speakers")
            print(f"   Predicted: {result.get('predicted_segments', 0)} segments, {result.get('predicted_speakers', 0)} speakers")
            
            if 'error' not in metrics:
                print(f"   📈 Segment Accuracy: {metrics.get('segment_accuracy', 0):.2%}")
                print(f"   📈 Speaker Count Accuracy: {metrics.get('speaker_count_accuracy', 0):.2%}")
                print(f"   📈 Time Coverage: {metrics.get('time_coverage', 0):.2%}")
            else:
                print(f"   ❌ Metrics Error: {metrics['error']}")
        
        # Overall summary
        successful_tests = [r for r in results if 'error' not in r and 'error' not in r.get('metrics', {})]
        if successful_tests:
            avg_segment_acc = np.mean([r['metrics']['segment_accuracy'] for r in successful_tests])
            avg_speaker_acc = np.mean([r['metrics']['speaker_count_accuracy'] for r in successful_tests])
            avg_coverage = np.mean([r['metrics']['time_coverage'] for r in successful_tests])
            
            print(f"\n🎯 OVERALL AVERAGES ({len(successful_tests)} tests)")
            print(f"   Segment Accuracy: {avg_segment_acc:.2%}")
            print(f"   Speaker Count Accuracy: {avg_speaker_acc:.2%}")
            print(f"   Time Coverage: {avg_coverage:.2%}")
        
        print(f"\n📁 Detailed results: {results_path}")
        print("="*70)

if __name__ == "__main__":
    main() 