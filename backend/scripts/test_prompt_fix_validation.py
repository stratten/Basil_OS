#!/usr/bin/env python3
"""Test the actual image processing service with the updated prompt to validate JSON formatting."""

import asyncio
import json
import time
from pathlib import Path

# Add project to path
import sys
sys.path.append(str(Path(__file__).parent / "Basil" / "src"))

from api.services.image_processing.image_processing_service import ImageProcessor
from api.core.services.model_service import ModelService
from api.core.models.model_manager import ModelManager
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
from api.core.models.reasoning.solar_model import SolarModel

async def test_image_processor_prompt_fix():
    """Test the updated prompt with actual ImageProcessor service."""
    
    print("🧪 Testing ImageProcessor with Updated Anti-Markdown Prompt")
    print("=" * 70)
    
    # Setup
    models_dir = Path.home() / ".basil" / "models"
    
    # Create ModelService with models directory
    model_service = ModelService(models_dir)
    model_service.initialize()
    
    # Create ImageProcessor
    image_processor = ImageProcessor(
        model_service=model_service,
        development_mode=True
    )
    
    # Test cases with different content types that might cause escaping issues
    test_cases = [
        {
            "name": "Twitter Scraper Test",
            "app_name": "Microsoft Edge", 
            "text": """Viral Content Discovery

🔥 Top Trending Topics:
- AI & Machine Learning developments
- Sustainable technology innovations  
- Remote work productivity tools

📊 Analytics Dashboard showing:
- 1.2M impressions this week
- 45% engagement rate increase
- Top performing hashtags: #TechTrends #Innovation

Recent Posts:
• "Breaking: New AI model achieves 95% accuracy"
• "Remote work tools that changed everything in 2024"
• "Sustainable tech startups to watch"

{Variables}: $analytics_data, %engagement_metrics%
Special chars: @mentions #hashtags [brackets] (parentheses)"""
        },
        {
            "name": "Code Editor Test",
            "app_name": "VS Code",
            "text": """// JavaScript function with template literals
function processData(data) {
    const result = `Processing ${data.length} items`;
    const config = {
        "api_key": "${API_KEY}",
        "timeout": 5000,
        "retry": true
    };
    
    // Handle JSON parsing
    try {
        const parsed = JSON.parse(response);
        return { success: true, data: parsed };
    } catch (error) {
        console.error('Parse error:', error);
        return { success: false, error: error.message };
    }
}

// Template with placeholders
const template = "Hello {name}, your score is {score}%";"""
        },
        {
            "name": "Simple Browser Test", 
            "app_name": "Safari",
            "text": "GitHub - exploring open source repositories for machine learning projects"
        }
    ]
    
    # Test with both models
    models_to_test = [
        {"name": "Llama-3.2-3B", "type": "Llama", "variant": "llama32-3b-instruct"},
        {"name": "Solar", "type": "Solar", "variant": "solar"}
    ]
    
    results = []
    
    for model_config in models_to_test:
        print(f"\n📋 Testing with {model_config['name']}")
        print("-" * 50)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n🧪 Test {i}: {test_case['name']}")
            
            try:
                # Test the actual analyze_text_only method
                start_time = time.time()
                
                result = await image_processor.analyze_text_only(
                    extracted_text=test_case["text"],
                    app_name=test_case["app_name"],
                    model_id=f"{model_config['type']}-{model_config['variant']}"
                )
                
                processing_time = time.time() - start_time
                
                # Check if analysis succeeded
                analysis = result.get("analysis")
                if analysis and hasattr(analysis, 'activity_type'):
                    json_valid = True
                    activity_type = analysis.activity_type
                    context = analysis.context
                    print(f"✅ JSON parsing: SUCCESS")
                    print(f"   Activity: {activity_type}")
                    print(f"   Context: {context[:80]}...")
                else:
                    json_valid = False
                    print(f"❌ JSON parsing: FAILED")
                    print(f"   Error: {result.get('error', 'Unknown error')}")
                
                print(f"⏰ Processing time: {processing_time:.2f}s")
                
                results.append({
                    "model": model_config["name"],
                    "test": test_case["name"],
                    "success": json_valid,
                    "time": processing_time,
                    "activity_type": activity_type if json_valid else "error"
                })
                
            except Exception as e:
                print(f"❌ Test failed: {e}")
                results.append({
                    "model": model_config["name"],
                    "test": test_case["name"], 
                    "success": False,
                    "time": 0,
                    "error": str(e)
                })
    
    # Summary
    print("\n📊 RESULTS SUMMARY")
    print("=" * 70)
    
    by_model = {}
    for result in results:
        model = result["model"]
        if model not in by_model:
            by_model[model] = {"total": 0, "success": 0, "avg_time": 0}
        
        by_model[model]["total"] += 1
        if result["success"]:
            by_model[model]["success"] += 1
        by_model[model]["avg_time"] += result["time"]
    
    for model, stats in by_model.items():
        success_rate = (stats["success"] / stats["total"]) * 100
        avg_time = stats["avg_time"] / stats["total"]
        status = "✅" if success_rate == 100 else "⚠️" if success_rate >= 67 else "❌"
        
        print(f"{status} {model}: {success_rate:.1f}% success ({stats['success']}/{stats['total']}) - {avg_time:.2f}s avg")
    
    # Check for any formatting/escaping issues
    print(f"\n🔍 Formatting Validation:")
    formatting_issues = []
    for result in results:
        if "error" in result:
            if "format" in result["error"].lower() or "escape" in result["error"].lower():
                formatting_issues.append(f"{result['model']}: {result['error']}")
    
    if formatting_issues:
        print("❌ Formatting issues detected:")
        for issue in formatting_issues:
            print(f"   - {issue}")
    else:
        print("✅ No formatting/escaping issues detected")
    
    return results

if __name__ == "__main__":
    asyncio.run(test_image_processor_prompt_fix()) 