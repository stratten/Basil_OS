# Transcription Accuracy Testing

This directory contains tools for measuring and improving transcription accuracy in Basil without adding dependencies to the main application.

## Overview

The transcription testing framework allows you to:
- Test actual production API endpoints 
- Measure Word Error Rate (WER) objectively
- Compare accuracy before/after improvements
- Use curated test datasets with known ground truth
- Generate detailed reports for analysis

## Quick Start

1. **Download test datasets:**
   ```bash
   python Basil/tests/services/tanscription_tests/download_test_datasets.py --dataset small
   ```

2. **Run accuracy tests:**
   ```bash
   python Basil/tests/services/tanscription_tests/transcription_accuracy_tester.py --test-set small
   ```

3. **Compare results before/after changes:**
   ```bash
   # Test before changes
   python transcription_accuracy_tester.py --test-set small --output before_improvements.json
   
   # Make improvements to the system
   # ...
   
   # Test after changes  
   python transcription_accuracy_tester.py --test-set small --output after_improvements.json
   ```

## Tools

### download_test_datasets.py

Downloads curated audio samples with known transcripts for testing.

**Usage:**
```bash
# Quick test (1 sample)
python download_test_datasets.py --dataset quick

# Small test set (5 samples) 
python download_test_datasets.py --dataset small

# Accent variety tests
python download_test_datasets.py --dataset accents

# Challenging conditions
python download_test_datasets.py --dataset challenging

# All datasets
python download_test_datasets.py --dataset all

# List available datasets
python download_test_datasets.py --list

# Clean up downloaded files
python download_test_datasets.py --clean
```

**Test Datasets:**
- **quick**: 1 sample for rapid testing
- **small**: 5 samples covering basic scenarios  
- **accents**: Different English accents (British, Australian, etc.)
- **challenging**: Difficult conditions (noise, fast speech)
- **all**: Downloads all datasets

### transcription_accuracy_tester.py

Tests transcription accuracy by calling the production API and measuring WER.

**Usage:**
```bash
# Quick test 
python transcription_accuracy_tester.py --test-set quick

# Small test set
python transcription_accuracy_tester.py --test-set small  

# Full test suite
python transcription_accuracy_tester.py --test-set full

# Custom API URL
python transcription_accuracy_tester.py --api-url http://localhost:8080

# Save results to specific file
python transcription_accuracy_tester.py --test-set small --output my_results.json
```

## Understanding Results

### Word Error Rate (WER)

WER measures transcription accuracy as a percentage:
- **WER = (Substitutions + Deletions + Insertions) / Total Words × 100**
- **Lower is better** (0% = perfect transcription)

**Grading Scale:**
- 🎯 **Excellent**: < 5% WER
- ✅ **Good**: 5-10% WER  
- ⚠️ **Fair**: 10-20% WER
- ❌ **Needs Improvement**: > 20% WER

### Sample Output

```
📊 TEST SUMMARY
==================================================
Test Set: small
Timestamp: 2024-01-15 14:30:22
Samples Tested: 5/5
Average WER: 8.2%
Average Time: 1.4s
Overall Grade: ✅ GOOD
```

### Individual Results

Each test shows:
```
📋 Testing: Clear American English
  📝 Expected: 'she had your dark suit in greasy wash water all year'
  🎤 Got:      'she had your dark suit in greasy wash water all year'  
  📊 WER:      0.00%
  ⏱️  Time:     1.2s
```

## Integration with Development Workflow

### Before Making Changes
1. Run baseline accuracy test:
   ```bash
   python transcription_accuracy_tester.py --test-set small --output baseline.json
   ```

### After Making Changes
1. Run the same test:
   ```bash
   python transcription_accuracy_tester.py --test-set small --output improved.json
   ```

2. Compare results by examining the JSON files or running both tests

### Recommended Testing Strategy

1. **Development**: Use `--test-set quick` for rapid iteration
2. **Pre-commit**: Use `--test-set small` for comprehensive validation  
3. **Release**: Use `--test-set full` for thorough testing
4. **Regression**: Use all test sets to ensure no quality degradation

## File Structure

```
Basil/tests/services/tanscription_tests/
├── README_transcription_testing.md          # This file
├── download_test_datasets.py                # Dataset downloader
├── transcription_accuracy_tester.py         # Accuracy tester
├── test_audio_samples/                      # Downloaded audio files
│   ├── test_config.json                     # Test configuration
│   ├── clear_speech.wav                     # Audio samples
│   ├── technical_terms.wav
│   └── ...
└── transcription_test_results_*.json        # Test results
```

## Technical Details

### API Testing
- Tests actual production endpoint: `POST /transcribe`
- Sends real audio files as multipart/form-data
- Measures end-to-end performance including network latency
- No mocking - tests the complete pipeline

### WER Calculation
- Normalizes text (lowercase, removes punctuation)
- Uses difflib for edit distance calculation
- Counts substitutions, deletions, and insertions
- Standard speech recognition accuracy metric

### No Dependencies
- Uses only Python standard library (json, urllib, pathlib, etc.)
- Won't add bloat to the main application
- Can be run independently of the main codebase

## Troubleshooting

### Common Issues

**Audio files not found:**
```
⚠️ Audio file not found: test_audio_samples/clear_speech.wav  
💡 Run: python download_test_datasets.py --dataset small
```
**Solution**: Download the test datasets first.

**API connection failed:**
```
❌ API call failed: Connection refused
```
**Solution**: Ensure the Basil backend is running on the specified URL.

**All tests fail with HTTP 500:**
```
❌ API error: 500
```
**Solution**: Check backend logs for transcription service errors.

### Debugging

1. **Check API health:**
   ```bash
   curl http://localhost:8000/health
   ```

2. **Test API manually:**
   ```bash
   curl -X POST -F "audio=@test_audio_samples/clear_speech.wav" http://localhost:8000/transcribe
   ```

3. **Check test data:**
   ```bash
   python download_test_datasets.py --list
   ```

## Future Enhancements

- **Real-time accuracy testing** during live transcription
- **Batch testing** with custom audio files
- **Performance regression detection** with automated alerts
- **Model comparison** testing (e.g., Whisper vs. alternative models)
- **Language-specific** test datasets beyond English 