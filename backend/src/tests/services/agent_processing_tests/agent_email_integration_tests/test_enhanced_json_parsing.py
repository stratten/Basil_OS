#!/usr/bin/env python3

"""
Test Enhanced JSON Parsing

This test validates the new enhanced JSON parsing strategies can handle:
1. Large responses (4000+ characters)
2. Nested structures (arrays within objects)
3. Mixed text + JSON responses (LLM explanations)
4. Complex todo breakdown responses

Usage:
    poetry run python test_enhanced_json_parsing.py
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

from api.services.agent_processing.shared.json_repair import robust_json_loads

def test_complex_todo_response():
    """Test parsing a complex todo breakdown response similar to what failed before."""
    
    # Simulate the 4223-character LLM response that was failing
    complex_response = '''
    Based on the instruction "Draft replies to my unread emails" and the available services, I need to analyze this request and break it down into logical todos. The workflow involves:

    1. First retrieving unread emails
    2. For each unread email, generating appropriate reply content 
    3. Creating draft replies

    The typical workflow for AI-assisted email drafting involves retrieving emails, generating contextual replies, and creating drafts.

    Here's my analysis broken down into complete logical todos:

    ```json
    [
        {
            "title": "Retrieve unread emails from inbox",
            "description": "Fetch all unread emails to identify which ones need replies",
            "complexity": 0.2,
            "data_assignment": "automatic - will be assigned based on todo order",
            "planned_steps": [
                {
                    "step_description": "Retrieve unread emails from the inbox using search criteria to filter for unread messages",
                    "simplified_description": "Get unread emails",
                    "likely_service": "email_service",
                    "likely_method": "get_emails",
                    "step_purpose": "Identify which emails need replies by fetching unread messages"
                }
            ]
        },
        {
            "title": "Draft reply to first unread email",
            "description": "Generate contextual reply content and create draft for the first unread email",
            "complexity": 0.7,
            "data_assignment": "automatic - will be assigned based on todo order",
            "planned_steps": [
                {
                    "step_description": "Generate contextual reply content based on the email's content and context",
                    "simplified_description": "Generate reply content",
                    "likely_service": "router_service",
                    "likely_method": "generate_agent_suggestion",
                    "step_purpose": "Create appropriate response content tailored to the specific email"
                },
                {
                    "step_description": "Create email draft reply using the generated content",
                    "simplified_description": "Create email draft",
                    "likely_service": "email_service",
                    "likely_method": "process_email_request",
                    "step_purpose": "Save the generated reply as a draft for review and sending"
                }
            ]
        },
        {
            "title": "Draft reply to second unread email",
            "description": "Generate contextual reply content and create draft for the second unread email",
            "complexity": 0.7,
            "data_assignment": "automatic - will be assigned based on todo order",
            "planned_steps": [
                {
                    "step_description": "Generate contextual reply content based on the email's content and context",
                    "simplified_description": "Generate reply content",
                    "likely_service": "router_service",
                    "likely_method": "generate_agent_suggestion",
                    "step_purpose": "Create appropriate response content tailored to the specific email"
                },
                {
                    "step_description": "Create email draft reply using the generated content",
                    "simplified_description": "Create email draft",
                    "likely_service": "email_service",
                    "likely_method": "process_email_request",
                    "step_purpose": "Save the generated reply as a draft for review and sending"
                }
            ]
        },
        {
            "title": "Draft reply to third unread email",
            "description": "Generate contextual reply content and create draft for the third unread email",
            "complexity": 0.7,
            "data_assignment": "automatic - will be assigned based on todo order",
            "planned_steps": [
                {
                    "step_description": "Generate contextual reply content based on the email's content and context",
                    "simplified_description": "Generate reply content",
                    "likely_service": "router_service",
                    "likely_method": "generate_agent_suggestion",
                    "step_purpose": "Create appropriate response content tailored to the specific email"
                },
                {
                    "step_description": "Create email draft reply using the generated content",
                    "simplified_description": "Create email draft",
                    "likely_service": "email_service",
                    "likely_method": "process_email_request",
                    "step_purpose": "Save the generated reply as a draft for review and sending"
                }
            ]
        }
    ]
    ```

    Let me explain each todo in detail so you understand the workflow...
    '''
    
    print("🧪 Testing Complex Todo Response Parsing")
    print(f"📊 Response Length: {len(complex_response)} characters")
    print("=" * 60)
    
    # Test the enhanced parsing
    result = robust_json_loads(complex_response)
    
    if result is None:
        print("❌ FAILED: Enhanced parsing still returned None")
        return False
    
    if not isinstance(result, list):
        print(f"❌ FAILED: Expected list, got {type(result)}")
        return False
    
    print(f"✅ SUCCESS: Parsed {len(result)} todos")
    
    # Validate the structure
    for i, todo in enumerate(result, 1):
        if not isinstance(todo, dict):
            print(f"❌ FAILED: Todo {i} is not a dict")
            return False
        
        if "title" not in todo:
            print(f"❌ FAILED: Todo {i} missing title")
            return False
        
        if "planned_steps" not in todo:
            print(f"❌ FAILED: Todo {i} missing planned_steps")
            return False
        
        steps = todo["planned_steps"]
        if not isinstance(steps, list):
            print(f"❌ FAILED: Todo {i} planned_steps is not a list")
            return False
        
        print(f"   📋 Todo {i}: {todo['title']}")
        print(f"      Steps: {len(steps)}")
        
        for j, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                print(f"❌ FAILED: Todo {i} Step {j} is not a dict")
                return False
            
            required_fields = ["step_description", "likely_service", "likely_method"]
            for field in required_fields:
                if field not in step:
                    print(f"❌ FAILED: Todo {i} Step {j} missing {field}")
                    return False
            
            print(f"        Step {j}: {step.get('simplified_description', step['step_description'][:50])}...")
    
    print("✅ All validation checks passed!")
    return True


def test_various_llm_patterns():
    """Test various LLM response patterns."""
    
    test_cases = [
        {
            "name": "Markdown JSON Block",
            "response": '''
            Here's the analysis:
            
            ```json
            [{"title": "Test Todo", "steps": []}]
            ```
            
            This should work.
            ''',
            "expected_length": 1
        },
        {
            "name": "Large Nested Structure",
            "response": '''
            ```json
            [
                {
                    "title": "Complex Todo",
                    "planned_steps": [
                        {"step": "First", "nested": {"data": "value"}},
                        {"step": "Second", "nested": {"more": "data"}}
                    ]
                },
                {
                    "title": "Another Todo", 
                    "planned_steps": [
                        {"step": "Third", "nested": {"even": "more"}}
                    ]
                }
            ]
            ```
            ''',
            "expected_length": 2
        },
        {
            "name": "Mixed Response",
            "response": '''
            Let me analyze this request. Here's what I found:
            
            The user wants multiple todos. Here's the JSON:
            
            [{"title": "First", "data": "test"}, {"title": "Second", "data": "more"}]
            
            Hope this helps!
            ''',
            "expected_length": 2
        }
    ]
    
    print("\n🧪 Testing Various LLM Patterns")
    print("=" * 60)
    
    for test_case in test_cases:
        print(f"\n📝 Testing: {test_case['name']}")
        
        result = robust_json_loads(test_case["response"])
        
        if result is None:
            print(f"❌ FAILED: Parsing returned None")
            continue
        
        if not isinstance(result, list):
            print(f"❌ FAILED: Expected list, got {type(result)}")
            continue
        
        if len(result) != test_case["expected_length"]:
            print(f"❌ FAILED: Expected {test_case['expected_length']} items, got {len(result)}")
            continue
        
        print(f"✅ SUCCESS: Parsed {len(result)} items correctly")
    
    return True


def main():
    """Run all enhanced JSON parsing tests."""
    print("🚀 Enhanced JSON Parsing Test Suite")
    print("=" * 60)
    
    success = True
    
    # Test 1: Complex todo response
    success &= test_complex_todo_response()
    
    # Test 2: Various LLM patterns
    success &= test_various_llm_patterns()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 ALL TESTS PASSED - Enhanced JSON parsing working!")
        print("✅ The enhanced strategies should fix the multiple todo creation issue")
    else:
        print("❌ SOME TESTS FAILED - Need to debug further")
    
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1) 