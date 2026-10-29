#!/usr/bin/env python3
"""
Activity Processing Performance Test

This script tests all available local reasoning models against a real activity processing 
scenario to compare speed and output quality. Essential for optimizing background processing
that needs to handle 480+ activities overnight.

Usage:
    poetry run python tests/core/model_tests/test_activity_processing_performance.py
"""

import os
import sys
import asyncio
import logging
import time
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Add the Basil directory to the Python path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASIL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
SRC_PATH = os.path.join(BASIL_ROOT, "src")
sys.path.insert(0, SRC_PATH)

# Import required modules
from api.core.models.model_manager import ModelManager
from api.core.models.model_types import ModelCapability
from api.core.models.base_model import ModelState

# Sample real activity data (from actual logs)
SAMPLE_ACTIVITY_DATA = {
    "app_name": "Microsoft Edge",
    "window_title": "Twitter Scraper - Viral Content Discovery - Microsoft Edge",
    "extracted_text": """Viral Content Discovery

🔥 Top Trending Topics:
- AI & Machine Learning developments
- Sustainable technology innovations  
- Remote work productivity tools
- Cryptocurrency market updates
- Health & wellness trends

📊 Analytics Dashboard
Engagement Rate: 87.3%
Reach: 2.4M users
Click-through Rate: 12.8%
Average Session: 4m 32s

💡 Content Recommendations:
• "10 AI Tools That Will Change Your Workflow" - High engagement potential
• "The Future of Remote Collaboration" - Trending topic match
• "Crypto Market Analysis: What's Next?" - Financial interest spike

🎯 Trending Hashtags:
#AIRevolution #TechInnovation #RemoteWork #CryptoNews #HealthTech

📈 Performance Metrics:
Total Posts Analyzed: 15,847
Viral Potential Score: 8.9/10
Audience Sentiment: 78% Positive
Peak Activity Time: 2-4 PM EST

⚡ Quick Actions:
[Schedule Post] [Analyze Competitor] [Export Data] [Set Alerts]

Recent Activity:
- Post about AI coding assistant gained 847 shares
- Remote work setup guide reached 5.2K views
- Crypto analysis thread got 234 comments
- Health tech review received 1.1K likes

Content Categories:
Technology (45%) | Business (23%) | Health (18%) | Finance (14%)

Engagement by Platform:
Twitter: 2.1M impressions
LinkedIn: 890K views  
Reddit: 445K upvotes
TikTok: 1.3M views""",
    "timestamp": "2025-07-08T21:44:54.362600"
}

# Test suite with varied OCR quality and edge cases
TEST_ACTIVITIES = [
    # Test 1: Clean social media (baseline from SAMPLE_ACTIVITY_DATA)
    {
        **SAMPLE_ACTIVITY_DATA,
        "name": "Clean Social Media",
        "difficulty": "easy"
    },
    
    # Test 2: Code with curly braces and special characters (CRITICAL for developers)
    {
        "name": "Code with Braces",
        "difficulty": "hard",
        "app_name": "Visual Studio Code",
        "window_title": "app.js - myproject",
        "extracted_text": """// Authentication middleware
function authenticateUser(req, res, next) {
    const token = req.headers['authorization'];
    if (!token) {
        return res.status(401).json({ error: 'No token provided' });
    }
    
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.user = { id: decoded.userId, role: decoded.role };
    next();
}

const userQuery = {
    where: { active: true, role: { in: ['admin', 'moderator'] } },
    select: { id: true, email: true }
};""",
        "timestamp": "2025-10-15T14:23:11.123456"
    },
    
    # Test 3: Poor OCR - spacing issues and typos
    {
        "name": "Poor OCR Quality",
        "difficulty": "medium",
        "app_name": "Adobe Acrobat",
        "window_title": "Quarterly_Report.pdf",
        "extracted_text": """Q uarterly F inancial Report  -  Q3  2025

Revenue: $2.4M   (+18% YoY)
Net  Profit: $500K

Key  Metrics:
- Customer  acquisit ion: 1,247  new  users
- Churn  rate: 3.2%

Market  Analysis:
Competitive  landscape  shows  strong  growth  in  SaaS  sector.""",
        "timestamp": "2025-09-20T09:15:33.987654"
    },
    
    # Test 4: JSON/API data with nested structures
    {
        "name": "API JSON Data",
        "difficulty": "hard",
        "app_name": "Postman",
        "window_title": "POST /api/users",
        "extracted_text": """POST /api/users HTTP/1.1

Request Body:
{
  "user": {
    "name": "John O'Brien",
    "email": "john@example.com",
    "preferences": {
      "notifications": true,
      "theme": "dark"
    }
  }
}

Response (200 OK):
{
  "success": true,
  "message": "User created successfully",
  "data": { "id": "usr_123abc" }
}""",
        "timestamp": "2025-10-30T16:45:30.555555"
    },
    
    # Test 5: Terminal with special characters
    {
        "name": "Terminal Agent Tasks",
        "difficulty": "medium",
        "app_name": "iTerm2",
        "window_title": "zsh - ~/projects/basil",
        "extracted_text": """$ git status
On branch feature/model-improvements
Your branch is ahead of 'origin/main' by 3 commits.

Changes not staged:
  modified:   src/api/models/qwen_model.py

$ poetry run pytest tests/ -v
========== 47 passed in 12.3s ==========
Coverage: 87%

$ git commit -m "Add robust JSON parsing" """,
        "timestamp": "2025-10-30T15:22:41.777777"
    }
]

# Real activity processing prompt (from actual system)
# Optimized for models like Qwen that tend to be verbose - uses response priming to force direct JSON output
ACTIVITY_PROCESSING_PROMPT = """<|im_start|>system
You output JSON only. No thinking, no explanation, no examples - just the JSON object.
<|im_end|>
<|im_start|>user
Activity: App={app_name}, Window={window_title}, Time={timestamp}
Text: {extracted_text}

Respond with this exact JSON structure (fill in values, output nothing else):
{{
    "activity_type": "research|communication|development|analysis",
    "context": "what user was doing",
    "content_summary": "2-3 sentences",
    "entities": ["people/places/orgs"],
    "skills": ["skills used"],
    "topics": ["main themes"],
    "sentiment": "positive|negative|neutral",
    "complexity": number
}}
<|im_end|>
<|im_start|>assistant
{{"""

# Model configurations - Updated with correct names from MODELS_CONFIG
MODEL_CONFIGS = [
    # Skipping Qwen3-4B PyTorch - hangs during generation with MPS backend
    # {
    #     "name": "Qwen3-4B", 
    #     "model_type": "Qwen",
    #     "variant": "qwen3-4b",
    #     "search_patterns": ["qwen3-4b*"],
    #     "description": "Latest Qwen3-4B model with hybrid thinking modes (32K context)"
    # },
    {
        "name": "Qwen3-8B-Q4_K_M", 
        "model_type": "Qwen",  # Use Qwen type to match models_config.py
        "variant": "qwen3-8b-instruct-q4km",
        "search_patterns": ["Qwen3-8B-Q4_K_M*", "qwen3-8b-instruct-q4km*"],
        "description": "Qwen3-8B with Q4 quantization, optimized for M1 Macs (32K context)"
    },
    # Commenting out Solar to focus on getting Qwen reliable first
    # {
    #     "name": "Solar", 
    #     "model_type": "Solar", 
    #     "variant": "solar",
    #     "search_patterns": ["solar*"],
    #     "description": "SOLAR 10.7B Instruct model (4K context)"
    # },
    {
        "name": "Llama-3.2-3B", 
        "model_type": "Llama",
        "variant": "llama32-3b-instruct",
        "search_patterns": ["Llama-3.2-3B*"],
        "description": "Fast 3B parameter Llama model"
    },
    {
        "name": "Llama-3.1-8B-Q5_K_M", 
        "model_type": "Llama",
        "variant": "llama31-8b-instruct-q5km",
        "search_patterns": ["Meta-Llama-3.1-8B*"],
        "description": "High-quality 8B parameter Llama model with Q5_K_M quantization"
    },
    {
        "name": "DeepSeek-R1", 
        "model_type": "DeepSeek", 
        "variant": "deepseek-r1-qwen-7b",
        "search_patterns": ["deepseek*"],
        "description": "DeepSeek-R1-Distill-Qwen-7B reasoning model"
    },
    {
        "name": "Mistral-7B", 
        "model_type": "Mistral", 
        "variant": "mistral-7b-v03",
        "search_patterns": ["mistral*"],
        "description": "Mistral 7B v0.3 Instruct model"
    },
    # Commented out - extremely slow, not worth testing again
    # {
    #     "name": "Phi3.5-Mini", 
    #     "model_type": "Phi",
    #     "variant": "phi35-mini",
    #     "search_patterns": ["phi35*"],
    #     "description": "Microsoft Phi-3.5 Mini model"
    # },
]

@dataclass
class ModelPerformanceResult:
    """Results from testing a single model's performance."""
    model_name: str
    model_type: str
    model_path: str
    load_time: float
    generation_time: float
    total_time: float
    json_valid: bool
    response_length: int
    quality_score: int
    activities_per_hour: float
    overnight_capacity: float
    time_for_480: float
    raw_response: str

class ActivityProcessingPerformanceTester:
    """Tests all available local reasoning models for activity processing performance."""
    
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self.results: List[ModelPerformanceResult] = []
        
        # Create test prompts for all test activities (varied OCR quality and edge cases)
        self.test_prompts = []
        for activity in TEST_ACTIVITIES:
            prompt = ACTIVITY_PROCESSING_PROMPT.format(
                app_name=activity["app_name"],
                window_title=activity["window_title"],
                timestamp=activity["timestamp"],
                extracted_text=activity["extracted_text"]
            )
            self.test_prompts.append({
                "name": activity["name"],
                "difficulty": activity["difficulty"],
                "prompt": prompt,
                "activity": activity
            })
        
        print(f"✅ Initialized with {len(self.test_prompts)} test activities")
    
    def analyze_response_quality(self, response: str, parsed_json: Optional[Dict] = None) -> int:
        """Analyze response quality and return a score out of 100."""
        score = 0
        
        # Basic response checks (20 points)
        if response and len(response.strip()) > 10:
            score += 10
        if len(response) > 100:  # Substantial response
            score += 10
            
        # JSON validity (30 points)
        if parsed_json is not None:
            score += 30
            
            # Required fields check (40 points)
            required_fields = ["activity_type", "context", "content_summary", 
                             "entities", "skills", "topics", "sentiment", "complexity"]
            present_fields = sum(1 for field in required_fields if field in parsed_json)
            score += int((present_fields / len(required_fields)) * 40)
            
            # Data quality check (10 points)
            if parsed_json.get("activity_type") and parsed_json.get("content_summary"):
                if len(str(parsed_json.get("content_summary", ""))) > 20:
                    score += 10
        
        return min(score, 100)
    
    def extract_json_from_response(self, response: str) -> Optional[str]:
        """Extract JSON from a response that may contain markdown code blocks or extra text.
        
        Note: As of the llama.cpp chat completion fix, local models now output clean JSON.
        This method primarily handles edge cases and markdown-wrapped responses.
        """
        import re
        
        # Strategy 1: Look for JSON within markdown code blocks (```json ... ```)
        json_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        matches = re.findall(json_block_pattern, response)
        if matches:
            return matches[0].strip()
        
        # Strategy 2: Look for the first { to last } sequence (greedy JSON extraction)
        first_brace = response.find('{')
        last_brace = response.rfind('}')
        
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = response[first_brace:last_brace + 1].strip()
            # Verify it at least looks like our expected structure
            if '"activity_type"' in potential_json:
                return potential_json
        
        return None
    
    async def discover_available_models(self) -> List[Dict[str, str]]:
        """Discover all available local reasoning models."""
        print(f"\n🔍 Discovering models in: {self.models_dir}")
        
        if not self.models_dir.exists():
            print(f"❌ Models directory not found: {self.models_dir}")
            return []
            
        available_models = []
        
        # Check for specific model types we know about
        for config in MODEL_CONFIGS:
            # Look for matching files
            matching_files = []
            for pattern in config["search_patterns"]:
                matching_files.extend(list(self.models_dir.glob(pattern)))
            
            if matching_files:
                model_path = matching_files[0]  # Use first match
                available_models.append({
                    "name": config["name"],
                    "type": config["model_type"],
                    "path": str(model_path)
                })
                print(f"✅ Found {config['name']}: {model_path}")
            else:
                print(f"❌ Not found: {config['name']} (patterns: {config['search_patterns']})")
                
        print(f"\n📊 Total reasoning models found: {len(available_models)}")
        return available_models
    
    async def test_model(self, model_info: Dict[str, str]) -> Optional[ModelPerformanceResult]:
        """Test a single model's performance."""
        print(f"\n🧪 Testing {model_info['name']}")
        print(f"   Type: {model_info['type']}")
        print(f"   Path: {model_info['path']}")
        
        # Get the config for this model to find the variant
        model_config = None
        for config in MODEL_CONFIGS:
            if config["name"] == model_info["name"]:
                model_config = config
                break
        
        if not model_config:
            print(f"   ❌ Error: Could not find config for {model_info['name']}")
            return None
        
        try:
            # Create fresh ModelManager instance for each test
            manager = ModelManager(self.models_dir)
            
            # Register model classes (same as ModelService.initialize())
            from api.core.models.reasoning.qwen_model import QwenModel
            from api.core.models.reasoning.solar_model import SolarModel
            from api.core.models.reasoning.phi_model import PhiModel
            from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
            from api.core.models.reasoning.deepseek_model import DeepSeekModel
            from api.core.models.reasoning.mistral_model import MistralModel
            
            # Register the model classes
            manager.register_model_class("Qwen", QwenModel)
            manager.register_model_class("Solar", SolarModel) 
            manager.register_model_class("Microsoft", PhiModel)
            manager.register_model_class("Llama", LlamaCppModel)
            manager.register_model_class("DeepSeek", DeepSeekModel)
            manager.register_model_class("Mistral", MistralModel)
            # manager.register_model_class("Skywork", LlamaCppModel)  # Commented out - Skywork excluded from current priorities
            
            # Load model using the correct method signature
            print("   ⏳ Loading model...")
            start_time = time.time()
            
            # Use the model_type and variant from the config
            model_name = f"{model_config['model_type']}-{model_config['variant']}"
            
            model = await manager.load_model(
                model_name=model_name,
                model_type=model_config["model_type"],
                required_capabilities={ModelCapability.REASONING}
            )
            
            load_time = time.time() - start_time
            print(f"   ✅ Model loaded in {load_time:.2f}s")
            
            # Test generation on ALL test activities
            print(f"   🔄 Testing {len(self.test_prompts)} activities...")
            
            total_generation_time = 0
            all_responses = []
            failed_activities = []
            
            for idx, test_data in enumerate(self.test_prompts, 1):
                print(f"     [{idx}/{len(self.test_prompts)}] Testing: {test_data['name']} ({test_data['difficulty']})")
                start_time = time.time()
                
                try:
                    response = await asyncio.wait_for(
                        model.generate_response(
                            prompt=test_data['prompt'],
                            max_tokens=5000  # Generous limit to ensure Qwen can complete responses even with verbosity
                        ),
                        timeout=120.0  # 2 minute timeout per activity
                    )
                    gen_time = time.time() - start_time
                    total_generation_time += gen_time
                    all_responses.append({
                        "name": test_data['name'],
                        "difficulty": test_data['difficulty'],
                        "response": response,
                        "generation_time": gen_time,
                        "success": True
                    })
                    print(f"       ✅ Completed in {gen_time:.2f}s")
                    print(f"       📝 Full Response:")
                    print(f"       {'-' * 80}")
                    # Print response with proper indentation
                    for line in response.split('\n'):
                        print(f"       {line}")
                    print(f"       {'-' * 80}")
                except asyncio.TimeoutError:
                    print(f"       ❌ Timed out after 120s")
                    failed_activities.append(test_data['name'])
                    all_responses.append({
                        "name": test_data['name'],
                        "difficulty": test_data['difficulty'],
                        "response": None,
                        "generation_time": 120.0,
                        "success": False
                    })
                except Exception as e:
                    print(f"       ❌ Error: {e}")
                    failed_activities.append(test_data['name'])
                    all_responses.append({
                        "name": test_data['name'],
                        "difficulty": test_data['difficulty'],
                        "response": None,
                        "generation_time": 0,
                        "success": False
                    })
            
            # Calculate average times
            successful_responses = [r for r in all_responses if r['success']]
            if not successful_responses:
                print(f"   ❌ All activities failed")
                await manager.unload_model(model_name)
                return None
            
            avg_generation_time = total_generation_time / len(successful_responses)
            total_time = load_time + avg_generation_time
            
            print(f"   ✅ Completed {len(successful_responses)}/{len(all_responses)} activities")
            print(f"   📊 Avg generation time: {avg_generation_time:.2f}s")
            print(f"   📊 Total time per activity: {total_time:.2f}s")
            
            # Validate JSON responses and analyze quality for all successful activities
            print(f"   🔍 Validating responses...")
            valid_json_count = 0
            quality_scores = []
            
            for resp_data in successful_responses:
                response = resp_data['response']
                json_valid = False
                parsed_json = None
                
                try:
                    # Try to parse as-is
                    parsed_json = json.loads(response)
                    json_valid = True
                except json.JSONDecodeError as e:
                    # Try to extract JSON from wrapped response
                    extracted_json = self.extract_json_from_response(response)
                    if extracted_json:
                        try:
                            parsed_json = json.loads(extracted_json)
                            json_valid = True
                        except json.JSONDecodeError as e2:
                            print(f"\n   ⚠️  Failed to parse JSON for '{resp_data['name']}': {e2}")
                
                if json_valid:
                    valid_json_count += 1
                
                # Analyze quality
                quality = self.analyze_response_quality(response, parsed_json)
                quality_scores.append(quality)
                resp_data['json_valid'] = json_valid
                resp_data['quality_score'] = quality
            
            avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0
            json_success_rate = (valid_json_count / len(successful_responses)) * 100
            
            print(f"   📊 JSON valid: {valid_json_count}/{len(successful_responses)} ({json_success_rate:.1f}%)")
            print(f"   📈 Avg quality score: {avg_quality_score:.1f}/100")
            
            # Calculate throughput estimates
            activities_per_hour = 3600 / total_time if total_time > 0 else 0
            overnight_capacity = activities_per_hour * 8  # 8 hours overnight
            time_for_480 = (480 * total_time) / 3600  # Hours needed for 480 activities
            
            print(f"   🚀 Throughput: {activities_per_hour:.1f} activities/hour")
            print(f"   🌙 Overnight capacity: {overnight_capacity:.0f} activities")
            print(f"   ⏰ Time for 480 activities: {time_for_480:.1f} hours")
            
            # Show per-activity breakdown
            print(f"\n   📋 Per-Activity Results:")
            for resp_data in successful_responses:
                status = "✅" if resp_data['json_valid'] else "❌"
                print(f"      {status} {resp_data['name']:20s} | Quality: {resp_data['quality_score']:3d}/100 | Time: {resp_data['generation_time']:5.1f}s")
                
                # If JSON validation failed, show the response for debugging
                if not resp_data['json_valid']:
                    print(f"         ⚠️  Raw response (first 500 chars):")
                    print(f"         {resp_data['response'][:500]}")
            
            if failed_activities:
                print(f"\n   ❌ Failed Activities: {', '.join(failed_activities)}")
            
            # Unload model to free memory
            await manager.unload_model(model_name)
            
            # Use the first successful response for compatibility with existing result structure
            first_response = successful_responses[0]['response']
            
            return ModelPerformanceResult(
                model_name=model_info["name"],
                model_type=model_info["type"],
                model_path=model_info["path"],
                load_time=load_time,
                generation_time=avg_generation_time,  # Use average across all activities
                total_time=total_time,
                json_valid=(valid_json_count == len(successful_responses)),  # All must be valid
                response_length=sum(len(r['response']) for r in successful_responses) // len(successful_responses),  # Average length
                quality_score=int(avg_quality_score),  # Average quality
                activities_per_hour=activities_per_hour,
                overnight_capacity=overnight_capacity,
                time_for_480=time_for_480,
                raw_response=first_response  # Keep first response for reference
            )
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return None
    
    async def run_performance_comparison(self) -> None:
        """Run performance comparison across all available models."""
        print("🚀 Activity Processing Performance Test")
        print("=" * 60)
        
        # Discover available models
        available_models = await self.discover_available_models()
        
        if not available_models:
            print("❌ No local reasoning models found for testing")
            return
        
        # Test each model
        for model_config in available_models:
            result = await self.test_model(model_config)
            if result:
                self.results.append(result)
        
        # Generate comparison report
        await self.generate_comparison_report()
    
    async def generate_comparison_report(self) -> None:
        """Generate a comprehensive comparison report."""
        if not self.results:
            print("❌ No successful model tests")
            return
            
        print("\n" + "=" * 80)
        print("📊 ACTIVITY PROCESSING PERFORMANCE COMPARISON")
        print("=" * 80)
        
        # Sort by total time (fastest first)
        sorted_results = sorted(self.results, key=lambda x: x.total_time)
        
        # Print summary table
        print(f"\n{'Model':<15} {'Load (s)':<10} {'Gen (s)':<10} {'Total (s)':<10} {'Acts/Hr':<10} {'Quality':<8} {'JSON':<6}")
        print("-" * 75)
        
        for result in sorted_results:
            json_status = "✅" if result.json_valid else "❌"
            print(f"{result.model_name:<15} {result.load_time:<10.2f} {result.generation_time:<10.2f} {result.total_time:<10.2f} {result.activities_per_hour:<10.1f} {result.quality_score:<8}/100 {json_status:<6}")
        
        # Detailed analysis
        print(f"\n📊 DETAILED PERFORMANCE ANALYSIS")
        print("-" * 40)
        
        fastest = sorted_results[0]
        print(f"🏆 Fastest Model: {fastest.model_name}")
        print(f"   - Total time: {fastest.total_time:.2f}s per activity")
        print(f"   - Throughput: {fastest.activities_per_hour:.1f} activities/hour")
        print(f"   - Overnight capacity: {fastest.overnight_capacity:.0f} activities")
        print(f"   - Time for 480 activities: {fastest.time_for_480:.1f} hours")
        
        # Find best quality
        best_quality = max(self.results, key=lambda x: x.quality_score)
        if best_quality != fastest:
            print(f"\n🎯 Highest Quality: {best_quality.model_name}")
            print(f"   - Quality score: {best_quality.quality_score}/100")
            print(f"   - Total time: {best_quality.total_time:.2f}s per activity")
        
        # Overnight processing analysis
        print(f"\n🌙 OVERNIGHT PROCESSING ANALYSIS")
        print("-" * 35)
        
        overnight_capable = [r for r in sorted_results if r.time_for_480 <= 8.0]
        if overnight_capable:
            print("✅ Models capable of processing 480 activities overnight (≤8 hours):")
            for result in overnight_capable:
                print(f"   - {result.model_name}: {result.time_for_480:.1f} hours ({result.activities_per_hour:.1f}/hr)")
        else:
            print("❌ No models can process 480 activities in 8 hours")
            print("   Fastest would need:")
            for result in sorted_results[:3]:
                print(f"   - {result.model_name}: {result.time_for_480:.1f} hours")
        
        # Save detailed results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = Path(__file__).parent / f"activity_processing_performance_{timestamp}.json"
        
        # Convert results to dict for JSON serialization
        results_data = {
            "timestamp": timestamp,
            "test_activities": TEST_ACTIVITIES,  # Include all test activity definitions
            "results": [
                {
                    "model_name": r.model_name,
                    "model_type": r.model_type,
                    "model_path": r.model_path,
                    "load_time": r.load_time,
                    "generation_time": r.generation_time,
                    "total_time": r.total_time,
                    "json_valid": r.json_valid,
                    "response_length": r.response_length,
                    "quality_score": r.quality_score,
                    "activities_per_hour": r.activities_per_hour,
                    "overnight_capacity": r.overnight_capacity,
                    "time_for_480": r.time_for_480,
                    "raw_response": r.raw_response
                }
                for r in self.results
            ]
        }
        
        with open(results_file, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"\n💾 Detailed results saved to: {results_file}")

async def main():
    """Main test function."""
    tester = ActivityProcessingPerformanceTester(Path.home() / ".basil" / "models")
    await tester.run_performance_comparison()

if __name__ == "__main__":
    asyncio.run(main()) 