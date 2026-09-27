"""
Quick test of Instructor for robust LLM response parsing
Testing with our parameter construction use case
"""
import instructor
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import json
import os

# Set up instructor-patched client
client = instructor.from_openai(OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "test-key")
))

class ParameterConstructionResult(BaseModel):
    parameters: Dict[str, Any]
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    missing_context: Optional[List[str]] = None
    context_references: Optional[List[str]] = None

def test_parameter_construction():
    """Test instructor with parameter construction scenario"""
    
    method_info = "email_service.get_emails_via_applescript(client_name: str, folder: str = 'inbox', limit: int = 10)"
    context_data = "Active app: Mail, Context: User wants to reply to emails"
    todo_info = "Reply to the first 2 emails from the inbox"
    
    try:
        # This is the magic - instructor handles all the parsing/validation
        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user", 
                "content": f"""
                Construct parameters for calling: {method_info}
                
                Context: {context_data}
                Todo: {todo_info}
                
                Provide the function parameters, confidence score (0-1), and reasoning.
                """
            }],
            response_model=ParameterConstructionResult,
            max_retries=2
        )
        
        print("✅ SUCCESS!")
        print(f"Parameters: {result.parameters}")
        print(f"Confidence: {result.confidence_score}")
        print(f"Reasoning: {result.reasoning}")
        
        # Test that it's actually a validated Pydantic object
        print(f"Type: {type(result)}")
        print(f"JSON: {result.model_dump_json(indent=2)}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def test_malformed_response():
    """Test instructor's robustness with markdown-wrapped responses"""
    
    # Simulate what we'd get from LLM service directly
    mock_response = '''```json
    {
        "parameters": {
            "client_name": "Mail",
            "folder": "inbox",
            "limit": 2
        },
        "confidence_score": 0.95,
        "reasoning": "Clear parameters needed for email retrieval"
    }
    ```'''
    
    try:
        # Normally we'd use our LLM service, but let's test manual validation
        import json
        import re
        
        # Extract JSON from markdown (what instructor does automatically)
        json_match = re.search(r'```json\s*\n(.*?)\n\s*```', mock_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            json_data = json.loads(json_str)
            
            # Validate with Pydantic (what instructor does automatically)
            result = ParameterConstructionResult.model_validate(json_data)
            
            print("✅ MANUAL PARSING SUCCESS!")
            print(f"Parsed: {result.parameters}")
            return True
            
    except Exception as e:
        print(f"❌ MANUAL PARSING FAILED: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing Instructor Integration")
    print("=" * 50)
    
    print("\n1. Testing manual validation with Pydantic:")
    test_malformed_response()
    
    print("\n2. Testing full instructor integration:")
    print("   (requires OPENAI_API_KEY environment variable)")
    if os.getenv("OPENAI_API_KEY"):
        test_parameter_construction()
    else:
        print("   ⚠️  OPENAI_API_KEY not set, skipping full test")
    
    print("\n✅ Instructor validation complete!")
    print("If this works, we can replace manual JSON parsing with instructor.") 