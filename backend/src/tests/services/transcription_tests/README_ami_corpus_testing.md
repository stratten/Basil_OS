# AMI Corpus Diarization Testing

This directory contains tools for testing speaker diarization functionality using the AMI Corpus, which is one of the gold standard datasets for speaker diarization evaluation.

## Overview

The AMI Corpus consists of 100 hours of meeting recordings with high-quality speaker diarization annotations. It's widely used in academic research for evaluating diarization systems.

## Files

- `test_ami_corpus_diarization.py` - Main test script for downloading AMI data and testing diarization
- `README_ami_corpus_testing.md` - This documentation file

## Prerequisites

Install required dependencies:
```bash
pip install requests aiohttp aiofiles
```

## Usage

### Quick Start

```bash
# List available meetings
python test_ami_corpus_diarization.py --list-meetings

# Quick test with one meeting
python test_ami_corpus_diarization.py --quick --download --test

# Download and test first 3 meetings
python test_ami_corpus_diarization.py --download --test
```

### Detailed Usage

```bash
# Download specific meeting
python test_ami_corpus_diarization.py --meeting ES2002a --download

# Test specific meeting (must be downloaded first)
python test_ami_corpus_diarization.py --meeting ES2002a --test-only

# Test multiple meetings
python test_ami_corpus_diarization.py --meetings ES2002a ES2002b --test-only

# Use custom API URL
python test_ami_corpus_diarization.py --api-url http://localhost:8001 --test-only

# Use custom test directory
python test_ami_corpus_diarization.py --test-dir ./my_ami_data --download --test
```

## Test Meetings

The script includes these pre-selected high-quality meetings:

1. **ES2002a** - 4 speakers, clear audio, good for initial testing
2. **ES2002b** - Same group, different meeting
3. **ES2002c** - Continuation of the series
4. **IS1000a** - Different scenario type
5. **IS1000b** - Different group dynamics
6. **TS3005a** - Technical discussion format
7. **TS3005b** - Follow-up technical meeting
8. **EN2001a** - English native speakers
9. **EN2001b** - Continuation
10. **IB4001** - Shorter meeting, good for quick tests

## Output

The script generates:

### Console Output
- Real-time progress during download and testing
- Summary of results including accuracy metrics
- Performance statistics

### JSON Results File
Saved to `{test_dir}/results/ami_diarization_results_{timestamp}.json`:

```json
{
  "test_timestamp": "2024-01-15 14:30:00",
  "api_url": "http://localhost:8000",
  "test_directory": "./ami_corpus_test_data",
  "results": {
    "ES2002a": {
      "duration": 1234.5,
      "processing_time": 45.2,
      "predicted_speakers": 4,
      "ground_truth_speakers": 4,
      "accuracy_metrics": {
        "segment_accuracy": 0.85,
        "time_coverage": 0.92,
        "speaker_count_accuracy": 1.0
      },
      "segments_count": 156
    }
  }
}
```

## Accuracy Metrics

The script calculates several diarization accuracy metrics:

- **Segment Accuracy** - Percentage of time where predicted speaker matches ground truth
- **Time Coverage** - Percentage of total time that has diarization coverage
- **Speaker Count Accuracy** - How accurately the number of speakers is detected
- **Processing Time** - Time taken to process the audio

## Data Structure

Downloaded data is organized as:
```
ami_corpus_test_data/
├── audio/
│   ├── ES2002a.Mix-Headset.wav
│   └── ES2002b.Mix-Headset.wav
├── annotations/
│   ├── ES2002a.rttm
│   └── ES2002b.rttm
└── results/
    └── ami_diarization_results_20240115_143000.json
```

## Understanding RTTM Format

The ground truth annotations use RTTM (Rich Transcription Time Marked) format:
```
SPEAKER filename channel start_time duration <NA> <NA> speaker_id <NA> <NA>
```

Example:
```
SPEAKER ES2002a 1 0.0 2.5 <NA> <NA> PM <NA> <NA>
SPEAKER ES2002a 1 2.5 1.8 <NA> <NA> ME <NA> <NA>
```

## Troubleshooting

### Download Issues
- Ensure internet connection is stable
- AMI Corpus servers may be slow - downloads can take time
- Some meetings may not be available - check the AMI website

### API Issues
- Ensure Basil backend is running on the specified URL
- Check that diarization is enabled in the backend configuration
- Verify the transcription endpoint accepts diarization parameters

### Performance Issues
- Large audio files (30-60 minutes) take significant processing time
- Consider testing with shorter meetings first (IB4001 is ~15 minutes)
- Monitor system resources during processing

## Expected Results

Good diarization performance typically shows:
- Segment accuracy: 70-90%
- Speaker count accuracy: 80-100%
- Time coverage: 85-95%

## Integration with Basil

This test script works with the Basil transcription API and expects:
- `/transcribe` endpoint that accepts `enable_diarization=true`
- Response format with speaker-attributed segments
- Support for WAV audio files

## Academic Use

The AMI Corpus is freely available for research purposes. If you use this data in academic work, please cite:

```
@inproceedings{carletta2005ami,
  title={The AMI meeting corpus: A pre-announcement},
  author={Carletta, Jean and Ashby, Simone and Bourban, Sebastien and Flynn, Mike and Guillemot, Mael and Hain, Thomas and Kadlec, Jaroslav and Karaiskos, Vasilis and Kraaij, Wessel and Kronenthal, Melissa and others},
  booktitle={International workshop on machine learning for multimodal interaction},
  pages={28--39},
  year={2005},
  organization={Springer}
}
``` 