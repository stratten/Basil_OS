#!/usr/bin/env python3
"""Direct test of the prompt fix without service layer complexity."""

import asyncio
import json
import time
from pathlib import Path

# Add project to path
import sys
sys.path.append(str(Path(__file__).parent / "Basil" / "src"))

from api.core.models.model_manager import ModelManager
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
from api.core.models.reasoning.solar_model import SolarModel

async def test_direct_prompt_fix():
    """Test the prompt fix by directly calling models."""
    
    print("🧪 Direct Prompt Fix Validation")
    print("=" * 50)
    
    # Setup
    models_dir = Path.home() / ".basil" / "models"
    manager = ModelManager(models_dir)
    manager.register_model_class("Llama", LlamaCppModel)
    manager.register_model_class("Solar", SolarModel)
    
    # Test with the updated prompt that mimics ImageProcessor
    test_prompt = """You are an AI assistant that analyzes user activities to build a comprehensive profile of their work and interests.
Analyze the content and provide a detailed understanding of what the user is doing.

Current Application: Microsoft Edge
Content:
Viral Content Discovery

🔥 Top Trending Topics:
- AI & Machine Learning developments
- Remote work productivity tools

Based on this content, provide a detailed analysis in JSON format with the following structure:

{{
  "activity_type": "The type of activity (coding, writing, browsing, communicating, etc.)",
  "context": "A brief description of what the user is doing",
  "content_summary": "A summary of the content visible in the window",
  "sentiment": "The user's apparent sentiment or focus state (optional)",
  "complexity": "Assessment of the complexity of the task (optional)"
}}

IMPORTANT GUIDELINES:
1. Focus on understanding what the user is doing, not suggesting what they should do next
2. Be comprehensive but concise in your analysis
3. Do not include any instructions or explanations outside the JSON structure
4. If you can't determine certain fields, use reasonable defaults or omit optional fields
5. Return valid JSON that can be parsed programmatically
6. Do NOT use markdown code blocks, backticks, or any markdown formatting - return raw JSON only"""
    
    # Test models
    models_to_test = [
        {"name": "Llama-3.2-3B", "type": "Llama", "variant": "llama32-3b-instruct"},
        {"name": "Solar", "type": "Solar", "variant": "solar"}
    ]
    
    results = []
    
    for model_config in models_to_test:
        print(f"\n📋 Testing {model_config['name']}")
        print("-" * 30)
        
        try:
            # Load model
            print("⏳ Loading model...")
            model = await manager.load_model(
                model_name=f"{model_config['type']}-{model_config['variant']}",
                model_type=model_config["type"],
                required_capabilities={ModelCapability.REASONING}
            )
            
            if not model:
                print("❌ Model loading failed")
                continue
                
            print("✅ Model loaded")
            
            # Test generation
            start_time = time.time()
            response = await model.generate_response(test_prompt, max_tokens=300)
            generation_time = time.time() - start_time
            
            print(f"⏰ Generation time: {generation_time:.2f}s")
            print(f"📄 Response length: {len(response)} chars")
            
            # Test JSON parsing
            response_clean = response.strip()
            
            # Check for markdown wrapping
            has_markdown = "```" in response_clean
            print(f"📝 Contains markdown: {'❌ YES' if has_markdown else '✅ NO'}")
            
            if has_markdown:
                print("   Raw response preview:")
                print(f"   {response_clean[:100]}...")
            
            # Try parsing JSON
            try:
                parsed = json.loads(response_clean)
                json_valid = True
                print("✅ Direct JSON parsing: SUCCESS")
                print(f"   Activity type: {parsed.get('activity_type', 'N/A')}")
                print(f"   Context: {parsed.get('context', 'N/A')[:50]}...")
            except json.JSONDecodeError as e:
                json_valid = False
                print(f"❌ Direct JSON parsing: FAILED ({e})")
                
                # Try cleaning markdown if present
                if has_markdown:
                    try:
                        # Remove code block markers
                        lines = response_clean.split('\n')
                        json_lines = []
                        in_json = False
                        
                        for line in lines:
                            if line.strip().startswith('```'):
                                in_json = not in_json
                                continue
                            if in_json or ('{' in line):
                                json_lines.append(line)
                        
                        cleaned_json = '\n'.join(json_lines).strip()
                        parsed = json.loads(cleaned_json)
                        json_valid = True
                        print("✅ After markdown cleanup: SUCCESS")
                    except json.JSONDecodeError:
                        print("❌ Even after cleanup: FAILED")
            
            results.append({
                "model": model_config["name"],
                "generation_time": generation_time,
                "has_markdown": has_markdown,
                "json_valid": json_valid,
                "response_length": len(response)
            })
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            results.append({
                "model": model_config["name"],
                "error": str(e)
            })
    
    # Summary
    print(f"\n📊 SUMMARY")
    print("=" * 50)
    
    for result in results:
        if "error" in result:
            print(f"❌ {result['model']}: ERROR - {result['error']}")
        else:
            status = "✅" if result["json_valid"] and not result["has_markdown"] else "⚠️"
            markdown_status = "No markdown" if not result["has_markdown"] else "Has markdown"
            json_status = "Valid JSON" if result["json_valid"] else "Invalid JSON"
            
            print(f"{status} {result['model']}: {markdown_status}, {json_status} ({result['generation_time']:.2f}s)")
    
    # Overall assessment
    successful_tests = [r for r in results if "error" not in r and r["json_valid"] and not r["has_markdown"]]
    total_tests = len([r for r in results if "error" not in r])
    
    if total_tests > 0:
        success_rate = len(successful_tests) / total_tests * 100
        print(f"\n🎯 Overall success rate: {success_rate:.1f}% ({len(successful_tests)}/{total_tests})")
        
        if success_rate == 100:
            print("✅ PROMPT FIX SUCCESSFUL - No markdown wrapping detected!")
        elif success_rate > 50:
            print("⚠️ PARTIAL SUCCESS - Some models still using markdown")
        else:
            print("❌ PROMPT FIX FAILED - Markdown wrapping still present")
    
    return results

if __name__ == "__main__":
    asyncio.run(test_direct_prompt_fix()) 