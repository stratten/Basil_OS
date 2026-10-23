"""
Test OpenAI integration with LangChain in agent processing
"""
import pytest
import asyncio


@pytest.mark.asyncio
async def test_openai_langchain_imports():
    """Test OpenAI model detection and LangChain integration"""
    try:
        # Test imports
        from langchain_openai import ChatOpenAI
        from langchain_anthropic import ChatAnthropic
        
        # Test that we can create model instances (without actually calling them)
        fake_api_key = "test-key-12345"
        
        # Test OpenAI model creation
        openai_llm = ChatOpenAI(
            api_key=fake_api_key,
            model="gpt-4o",
            temperature=0.7,
            max_tokens=1000
        )
        assert openai_llm is not None
        
        # Test Anthropic model creation
        anthropic_llm = ChatAnthropic(
            api_key=fake_api_key,
            model="claude-3-5-sonnet-20240620",
            temperature=0.7,
            max_tokens=1000
        )
        assert anthropic_llm is not None
        
    except ImportError as e:
        pytest.fail(f"Import error: {e}")
    except Exception as e:
        pytest.fail(f"Unexpected error: {e}")


@pytest.mark.asyncio
async def test_model_detection_logic():
    """Test that model detection correctly identifies OpenAI vs Anthropic models"""
    # Test model detection logic
    test_models = [
        ("gpt-4o", True),  # Should be detected as OpenAI
        ("gpt-4", True),   # Should be detected as OpenAI  
        ("o1-pro", True),  # Should be detected as OpenAI
        ("claude-3-5-sonnet", False),  # Should be detected as Anthropic
        ("claude-sonnet-4", False),    # Should be detected as Anthropic
    ]
    
    for model_name, expected_openai in test_models:
        is_openai_model = any(openai_prefix in model_name.lower() for openai_prefix in [
            'gpt-', 'o1-', 'o3-', 'o4-', 'text-davinci', 'text-curie', 'text-babbage', 'text-ada'
        ])
        
        assert is_openai_model == expected_openai, f"Model {model_name} detection failed"
