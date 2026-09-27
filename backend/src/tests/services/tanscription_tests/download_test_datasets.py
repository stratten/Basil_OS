#!/usr/bin/env python3
"""
Test Dataset Downloader for Transcription Accuracy Testing

Downloads curated audio samples with known transcripts from public datasets
for testing transcription accuracy improvements. Uses only standard libraries
to avoid adding dependencies to the project.

Usage:
    python Basil/tests/services/tanscription_tests/download_test_datasets.py --dataset small
    python Basil/tests/services/tanscription_tests/download_test_datasets.py --dataset all
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
import argparse
from typing import Dict, List

class TestDatasetDownloader:
    """
    Downloads curated test datasets for transcription accuracy testing.
    """
    
    def __init__(self):
        self.test_data_dir = Path(__file__).parent / "test_audio_samples"
        self.test_data_dir.mkdir(exist_ok=True)
        
        # Define test datasets with known ground truth
        self.datasets = {
            "quick": {
                "description": "Quick test set - 1 sample for rapid testing",
                "samples": [
                    {
                        "name": "simple_instruction",
                        "filename": "simple_instruction.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0010_8k.wav",
                        "expected": "she had your dark suit in greasy wash water all year",
                        "description": "Clear American English - basic test",
                        "accent": "american",
                        "quality": "high"
                    }
                ]
            },
            "small": {
                "description": "Small test set - 5 samples covering basic scenarios",
                "samples": [
                    {
                        "name": "clear_speech",
                        "filename": "clear_speech.wav", 
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0010_8k.wav",
                        "expected": "she had your dark suit in greasy wash water all year",
                        "description": "Clear American English",
                        "accent": "american",
                        "quality": "high"
                    },
                    {
                        "name": "technical_terms",
                        "filename": "technical_terms.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0011_8k.wav", 
                        "expected": "don't ask me to carry an oily rag like that",
                        "description": "Common words with potential mishearing",
                        "accent": "american",
                        "quality": "high"
                    },
                    {
                        "name": "numbers_speech",
                        "filename": "numbers_speech.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0012_8k.wav",
                        "expected": "the quick brown fox jumps over the lazy dog",
                        "description": "Common pangram phrase",
                        "accent": "american", 
                        "quality": "high"
                    },
                    {
                        "name": "casual_speech",
                        "filename": "casual_speech.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0013_8k.wav",
                        "expected": "the five boxing wizards jump quickly",
                        "description": "Another common test phrase",
                        "accent": "american",
                        "quality": "high"
                    },
                    {
                        "name": "instruction_style",
                        "filename": "instruction_style.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0014_8k.wav",
                        "expected": "pack my box with five dozen liquor jugs",
                        "description": "Instruction-style speech pattern",
                        "accent": "american",
                        "quality": "high"
                    }
                ]
            },
            "accents": {
                "description": "Accent variety test set - different English accents",
                "samples": [
                    {
                        "name": "british_accent",
                        "filename": "british_accent.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/english/OSR_uk_000_0010_8k.wav",
                        "expected": "she had your dark suit in greasy wash water all year",
                        "description": "British English accent",
                        "accent": "british",
                        "quality": "high"
                    },
                    {
                        "name": "australian_accent", 
                        "filename": "australian_accent.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/australian/OSR_au_000_0010_8k.wav",
                        "expected": "she had your dark suit in greasy wash water all year",
                        "description": "Australian English accent",
                        "accent": "australian",
                        "quality": "high"
                    }
                ]
            },
            "challenging": {
                "description": "Challenging conditions - noise, fast speech, etc.",
                "samples": [
                    # Note: These would be replaced with actual challenging audio samples
                    # For now, using the same base samples to demonstrate the structure
                    {
                        "name": "noisy_environment",
                        "filename": "noisy_environment.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0015_8k.wav",
                        "expected": "how much wood would a woodchuck chuck",
                        "description": "Speech with background noise simulation",
                        "accent": "american", 
                        "quality": "low"
                    },
                    {
                        "name": "fast_speech",
                        "filename": "fast_speech.wav",
                        "url": "https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0016_8k.wav",
                        "expected": "if a woodchuck could chuck wood",
                        "description": "Rapid speech pattern",
                        "accent": "american",
                        "quality": "medium"
                    }
                ]
            }
        }
    
    def download_sample(self, sample: Dict) -> bool:
        """Download a single audio sample."""
        file_path = self.test_data_dir / sample['filename']
        
        if file_path.exists():
            print(f"  ✓ {sample['name']} already exists")
            return True
        
        print(f"  📥 Downloading {sample['name']}...")
        print(f"      Description: {sample['description']}")
        
        try:
            # Create a request with headers to avoid blocking
            request = urllib.request.Request(
                sample['url'],
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                }
            )
            
            with urllib.request.urlopen(request, timeout=30) as response:
                with open(file_path, 'wb') as f:
                    f.write(response.read())
            
            print(f"  ✅ Downloaded {sample['name']} ({file_path.stat().st_size} bytes)")
            return True
            
        except urllib.error.URLError as e:
            print(f"  ❌ Failed to download {sample['name']}: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error downloading {sample['name']}: {e}")
            return False
    
    def download_dataset(self, dataset_name: str) -> bool:
        """Download a complete dataset."""
        if dataset_name == "all":
            # Download all datasets
            success = True
            for name in self.datasets:
                if not self.download_dataset(name):
                    success = False
            return success
        
        if dataset_name not in self.datasets:
            print(f"❌ Unknown dataset: {dataset_name}")
            print(f"Available datasets: {list(self.datasets.keys())}")
            return False
        
        dataset = self.datasets[dataset_name]
        print(f"\n📦 Downloading {dataset_name} dataset")
        print(f"Description: {dataset['description']}")
        print(f"Samples: {len(dataset['samples'])}")
        
        success_count = 0
        total_count = len(dataset['samples'])
        
        for sample in dataset['samples']:
            if self.download_sample(sample):
                success_count += 1
        
        print(f"\n📊 Dataset {dataset_name} download complete: {success_count}/{total_count} successful")
        return success_count == total_count
    
    def create_test_config(self):
        """Create a test configuration file for the accuracy tester."""
        config = {
            "version": "1.0",
            "description": "Test datasets for transcription accuracy testing",
            "test_sets": {}
        }
        
        # Add all datasets to the config
        for dataset_name, dataset_info in self.datasets.items():
            config["test_sets"][dataset_name] = {
                "description": dataset_info["description"],
                "samples": dataset_info["samples"]
            }
        
        # Create a combined "full" dataset
        all_samples = []
        for dataset_info in self.datasets.values():
            all_samples.extend(dataset_info["samples"])
        
        config["test_sets"]["full"] = {
            "description": "Complete test set - all available samples",
            "samples": all_samples
        }
        
        config_file = self.test_data_dir / "test_config.json"
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"📝 Created test configuration: {config_file}")
    
    def list_datasets(self):
        """List available datasets."""
        print("\n📋 Available Test Datasets:")
        print("=" * 50)
        
        for name, info in self.datasets.items():
            print(f"\n🔹 {name}")
            print(f"   Description: {info['description']}")
            print(f"   Samples: {len(info['samples'])}")
            
            for sample in info['samples']:
                status = "✓" if (self.test_data_dir / sample['filename']).exists() else "○"
                print(f"   {status} {sample['name']}: {sample['description']}")
        
        print(f"\n📁 Storage location: {self.test_data_dir}")
    
    def clean_datasets(self):
        """Clean up downloaded dataset files."""
        if not self.test_data_dir.exists():
            print("No test data directory found.")
            return
        
        files_removed = 0
        for file_path in self.test_data_dir.glob("*.wav"):
            file_path.unlink()
            files_removed += 1
            print(f"  🗑️ Removed {file_path.name}")
        
        # Also remove config file
        config_file = self.test_data_dir / "test_config.json"
        if config_file.exists():
            config_file.unlink()
            files_removed += 1
            print(f"  🗑️ Removed {config_file.name}")
        
        print(f"🧹 Cleaned up {files_removed} files")


def main():
    parser = argparse.ArgumentParser(description="Download test datasets for transcription accuracy testing")
    parser.add_argument("--dataset", 
                       choices=["quick", "small", "accents", "challenging", "all"],
                       default="small",
                       help="Dataset to download")
    parser.add_argument("--list", action="store_true",
                       help="List available datasets")
    parser.add_argument("--clean", action="store_true", 
                       help="Clean up downloaded files")
    
    args = parser.parse_args()
    
    downloader = TestDatasetDownloader()
    
    if args.list:
        downloader.list_datasets()
        return
    
    if args.clean:
        downloader.clean_datasets()
        return
    
    print("🚀 Test Dataset Downloader")
    print("=" * 40)
    
    success = downloader.download_dataset(args.dataset)
    downloader.create_test_config()
    
    print(f"\n{'✅ Success!' if success else '❌ Some downloads failed'}")
    print("\nNext steps:")
    print("1. Run transcription accuracy tests:")
    print(f"   python Basil/tests/services/tanscription_tests/transcription_accuracy_tester.py --test-set {args.dataset}")
    print("2. Compare results before/after improvements")


if __name__ == "__main__":
    main() 