#!/usr/bin/env python3
"""
Simple script to download AMI Corpus sample audio for testing.
This runs with system Python to access the datasets library.
"""

import os
import sys
from pathlib import Path
import numpy as np

def download_ami_sample(meeting_id="ES2002a", max_duration=30.0):
    """Download a sample of AMI Corpus audio"""
    try:
        from datasets import load_dataset
        import soundfile as sf
        
        print(f"📥 Loading AMI Corpus meeting: {meeting_id}")
        
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
        
        # Limit to specified duration
        audio_array = audio_array[:int(max_duration * sample_rate)]
        ground_truth_segments = [
            seg for seg in ground_truth_segments 
            if seg['start'] < max_duration
        ]
        
        # Adjust end times
        for seg in ground_truth_segments:
            seg['end'] = min(seg['end'], max_duration)
        
        print(f"📊 Ground truth: {len(ground_truth_segments)} segments from {len(set(seg['speaker'] for seg in ground_truth_segments))} speakers")
        
        # Save files
        output_dir = Path("diarization_test_data")
        output_dir.mkdir(exist_ok=True)
        
        audio_file = output_dir / f"real_ami_{meeting_id}.wav"
        annotations_file = output_dir / f"real_ami_{meeting_id}_annotations.json"
        
        # Save audio
        sf.write(audio_file, audio_array, sample_rate)
        
        # Save annotations
        import json
        annotations = {
            'meeting_id': meeting_id,
            'duration': max_duration,
            'sample_rate': sample_rate,
            'segments': ground_truth_segments,
            'speakers': list(set(seg['speaker'] for seg in ground_truth_segments))
        }
        
        with open(annotations_file, 'w') as f:
            json.dump(annotations, f, indent=2)
        
        print(f"✅ Saved audio: {audio_file}")
        print(f"✅ Saved annotations: {annotations_file}")
        
        return {
            'audio_file': str(audio_file),
            'annotations_file': str(annotations_file),
            'annotations': annotations
        }
        
    except ImportError:
        print("❌ 'datasets' library not available")
        return None
    except Exception as e:
        print(f"❌ Error downloading AMI sample: {e}")
        return None

if __name__ == "__main__":
    meeting_id = sys.argv[1] if len(sys.argv) > 1 else "ES2002a"
    result = download_ami_sample(meeting_id)
    if result:
        print(f"\n🎯 Ready for diarization testing!")
    else:
        print(f"\n❌ Download failed") 