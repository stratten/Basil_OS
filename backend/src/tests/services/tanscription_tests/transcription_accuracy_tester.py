#!/usr/bin/env python3
"""
Transcription Accuracy Testing Script

A lightweight tool to measure transcription accuracy improvements without adding
dependencies to the main application. Tests the actual production pipeline through
API calls and measures WER (Word Error Rate) and timing.

Usage:
    python Basil/tests/services/tanscription_tests/transcription_accuracy_tester.py --test-set small
    python Basil/tests/services/tanscription_tests/transcription_accuracy_tester.py --download-samples
"""

import os
import sys
import json
import time
import argparse
import requests
import urllib.request
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import difflib
import re

# Add the src directory to the path so we can import from the project
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

class TranscriptionAccuracyTester:
    """
    Tests transcription accuracy by comparing API results against known ground truth.
    """
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url
        self.test_data_dir = Path(__file__).parent / "test_audio_samples"
        self.test_data_dir.mkdir(exist_ok=True)
        
        # Load test samples from configuration if available
        self.test_samples = self._load_test_config()
        
    def _load_test_config(self) -> List[Dict]:
        """Load test samples from the dataset configuration."""
        config_file = self.test_data_dir / "test_config.json"
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    return config.get('test_sets', {}).get('small', {}).get('samples', [])
            except Exception as e:
                print(f"⚠️ Warning: Could not load test config: {e}")
        
        # Fallback to basic samples if no config found
        return [
            {
                "name": "fallback_sample",
                "filename": "fallback_sample.wav",
                "expected": "this is a fallback test sample",
                "description": "Fallback sample - run download_test_datasets.py first"
            }
        ]
    
    def _get_test_set_samples(self, test_set: str) -> List[Dict]:
        """Get samples for the specified test set."""
        config_file = self.test_data_dir / "test_config.json"
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    test_sets = config.get('test_sets', {})
                    
                    if test_set in test_sets:
                        return test_sets[test_set].get('samples', [])
                    else:
                        print(f"⚠️ Test set '{test_set}' not found, using 'small'")
                        return test_sets.get('small', {}).get('samples', [])
            except Exception as e:
                print(f"⚠️ Warning: Could not load test set config: {e}")
        
        # Fallback logic if no config
        if test_set == "quick":
            return self.test_samples[:1]
        elif test_set == "small":
            return self.test_samples[:3]
        else:  # full
            return self.test_samples

    def calculate_wer(self, reference: str, hypothesis: str) -> float:
        """
        Calculate Word Error Rate (WER) between reference and hypothesis text.
        WER = (S + D + I) / N
        Where S=substitutions, D=deletions, I=insertions, N=total words in reference
        """
        # Normalize text (lowercase, remove punctuation, split into words)
        ref_words = self._normalize_text(reference).split()
        hyp_words = self._normalize_text(hypothesis).split()
        
        # Use difflib to find the edit operations
        diff = list(difflib.unified_diff(ref_words, hyp_words, lineterm=''))
        
        # Count operations (simplified approach)
        substitutions = 0
        deletions = 0
        insertions = 0
        
        for line in diff:
            if line.startswith('-') and not line.startswith('---'):
                deletions += 1
            elif line.startswith('+') and not line.startswith('+++'):
                insertions += 1
        
        # For substitutions, we count pairs of - and + lines
        substitutions = min(deletions, insertions)
        deletions -= substitutions
        insertions -= substitutions
        
        total_errors = substitutions + deletions + insertions
        total_words = len(ref_words)
        
        if total_words == 0:
            return 0.0 if total_errors == 0 else float('inf')
        
        return (total_errors / total_words) * 100
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        # Convert to lowercase
        text = text.lower()
        # Remove punctuation and extra whitespace
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def download_test_samples(self):
        """Download test audio samples for accuracy testing."""
        print("📥 Downloading test audio samples...")
        
        for sample in self.test_samples:
            file_path = self.test_data_dir / f"{sample['name']}.wav"
            if not file_path.exists():
                print(f"  Downloading {sample['name']}...")
                try:
                    urllib.request.urlretrieve(sample['url'], file_path)
                    print(f"  ✅ Downloaded {sample['name']}")
                except Exception as e:
                    print(f"  ❌ Failed to download {sample['name']}: {e}")
            else:
                print(f"  ✓ {sample['name']} already exists")
    
    def test_api_endpoint(self, audio_file: Path) -> Tuple[Optional[str], float]:
        """Test transcription through the API endpoint."""
        print(f"  🎯 Testing API with {audio_file.name}...")
        
        start_time = time.time()
        
        try:
            # Call the transcription API (adjust endpoint as needed)
            with open(audio_file, 'rb') as f:
                files = {'audio': f}
                response = requests.post(
                    f"{self.api_base_url}/transcribe",
                    files=files,
                    timeout=30
                )
            
            end_time = time.time()
            
            if response.status_code == 200:
                result = response.json()
                # Extract transcription text (adjust based on your API response format)
                transcription = result.get('transcription', '')
                return transcription, end_time - start_time
            else:
                print(f"    ❌ API error: {response.status_code}")
                return None, end_time - start_time
                
        except Exception as e:
            end_time = time.time()
            print(f"    ❌ API call failed: {e}")
            return None, end_time - start_time
    
    def run_accuracy_tests(self, test_set: str = "small") -> Dict:
        """Run accuracy tests on the specified test set."""
        print(f"\n🧪 Running {test_set} accuracy test set...")
        
        results = {
            "test_set": test_set,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_samples": 0,
            "successful_tests": 0,
            "average_wer": 0.0,
            "average_time": 0.0,
            "individual_results": []
        }
        
        # Load test set from configuration
        samples_to_test = self._get_test_set_samples(test_set)
        
        total_wer = 0.0
        total_time = 0.0
        successful_tests = 0
        
        for sample in samples_to_test:
            print(f"\n📋 Testing: {sample['description']}")
            
            # Use filename from config, fallback to name.wav
            filename = sample.get('filename', f"{sample['name']}.wav")
            audio_file = self.test_data_dir / filename
            if not audio_file.exists():
                print(f"  ⚠️  Audio file not found: {audio_file}")
                print(f"  💡 Run: python Basil/tests/services/tanscription_tests/download_test_datasets.py --dataset all")
                continue
            
            # Test the API
            transcription, test_time = self.test_api_endpoint(audio_file)
            
            if transcription is not None:
                # Calculate WER
                wer = self.calculate_wer(sample['expected'], transcription)
                
                print(f"  📝 Expected: '{sample['expected']}'")
                print(f"  🎤 Got:      '{transcription}'")
                print(f"  📊 WER:      {wer:.2f}%")
                print(f"  ⏱️  Time:     {test_time:.2f}s")
                
                total_wer += wer
                total_time += test_time
                successful_tests += 1
                
                results["individual_results"].append({
                    "sample": sample['name'],
                    "expected": sample['expected'],
                    "transcription": transcription,
                    "wer": wer,
                    "time": test_time
                })
            
        # Calculate averages
        if successful_tests > 0:
            results["average_wer"] = total_wer / successful_tests
            results["average_time"] = total_time / successful_tests
            results["successful_tests"] = successful_tests
        
        results["total_samples"] = len(samples_to_test)
        
        return results
    
    def save_results(self, results: Dict, output_file: str = None):
        """Save test results to a JSON file."""
        if output_file is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_file = f"transcription_test_results_{timestamp}.json"
        
        output_path = Path(__file__).parent / output_file
        
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: {output_path}")
    
    def print_summary(self, results: Dict):
        """Print a summary of test results."""
        print(f"\n📊 TEST SUMMARY")
        print(f"{'='*50}")
        print(f"Test Set: {results['test_set']}")
        print(f"Timestamp: {results['timestamp']}")
        print(f"Samples Tested: {results['successful_tests']}/{results['total_samples']}")
        
        if results['successful_tests'] > 0:
            print(f"Average WER: {results['average_wer']:.2f}%")
            print(f"Average Time: {results['average_time']:.2f}s")
            
            # Grade the results
            if results['average_wer'] < 5:
                grade = "🎯 EXCELLENT"
            elif results['average_wer'] < 10:
                grade = "✅ GOOD"
            elif results['average_wer'] < 20:
                grade = "⚠️ FAIR"
            else:
                grade = "❌ NEEDS IMPROVEMENT"
            
            print(f"Overall Grade: {grade}")
        else:
            print("❌ No successful tests completed")


def main():
    parser = argparse.ArgumentParser(description="Test transcription accuracy")
    parser.add_argument("--test-set", choices=["quick", "small", "full"], 
                       default="quick", help="Test set size to run")
    parser.add_argument("--download-samples", action="store_true",
                       help="Download test audio samples")
    parser.add_argument("--api-url", default="http://localhost:8000",
                       help="Base URL for the API")
    parser.add_argument("--output", help="Output file for results")
    
    args = parser.parse_args()
    
    tester = TranscriptionAccuracyTester(api_base_url=args.api_url)
    
    if args.download_samples:
        tester.download_test_samples()
        return
    
    # Run the tests
    print("🚀 Starting Transcription Accuracy Tests")
    print(f"API URL: {args.api_url}")
    
    results = tester.run_accuracy_tests(args.test_set)
    tester.print_summary(results)
    tester.save_results(results, args.output)


if __name__ == "__main__":
    main() 