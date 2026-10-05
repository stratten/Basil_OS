"""
Cloud Reasoning Models Registry.

Contains cloud-based reasoning models (OpenAI, Anthropic, Gemini) and
provider-level display ordering for the cloud reasoning category.
"""

from typing import Any, Dict

from .schema import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    CloudReasoningConfig,
)


# =============================================================================
# PROVIDER DISPLAY ORDER - Controls provider group ordering in UI.
# =============================================================================

CLOUD_PROVIDER_DISPLAY_ORDER: Dict[str, int] = {
    PROVIDER_ANTHROPIC: 1,
    PROVIDER_OPENAI: 2,
    PROVIDER_GOOGLE: 3,
}


# =============================================================================
# CLOUD REASONING MODELS.
# =============================================================================

# Models will be migrated here from openai_model.py, claude_model.py, gemini_model.py.
# Once migrated, models are the source of truth and legacy hardcoded entries can be removed.

CLOUD_REASONING_MODELS: Dict[str, CloudReasoningConfig] = {
    # =========================================================================
    # OPENAI MODELS
    # =========================================================================
    # Ref: https://developers.openai.com/api/docs/models/gpt-5
    # -------------------------------------------------------------------------
    # GPT-5 - Previous flagship reasoning model.
    # -------------------------------------------------------------------------
    "gpt-5": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",  # minimal, low, medium, high
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "medium",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5",
        "description": "Previous intelligent reasoning model for coding and agentic tasks with configurable reasoning effort",
        "display_order": 2,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5-mini": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5 Mini",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "medium",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5-mini",
        "description": "Cost-effective GPT-5 variant for everyday reasoning tasks",
        "display_order": 3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5-nano": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5 Nano",
        "capabilities": ["reasoning"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "low",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5-nano",
        "description": "Fastest and most affordable GPT-5 variant for simple tasks",
        "display_order": 4,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-5.1 - Current recommended model (per OpenAI docs).
    # -------------------------------------------------------------------------
    "gpt-5.1": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.1",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "medium",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.1",
        "description": "Current recommended GPT model with improved reasoning and coding capabilities",
        "display_order": 1,
        "default_enabled": True,
        "recommended": True,
        "recommended_reason": "OpenAI's recommended model for most tasks",
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-5.2 - Latest model (February 2026).
    # -------------------------------------------------------------------------
    "gpt-5.2": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.2",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["minimal", "low", "medium", "high", "max"],
                "default": "high",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.2",
        "description": "Latest GPT model with enhanced reasoning and newest capabilities",
        "display_order": 0,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.2-pro": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.2 Pro",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["minimal", "low", "medium", "high", "max"],
                "default": "high",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.2-pro",
        "description": "Higher-accuracy GPT-5.2 tier for complex agentic coding and long-context reasoning",
        "display_order": -3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.4-mini": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.4 Mini",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "file_search",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high"],
                "default": "medium",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.4-mini",
        "description": "Efficient GPT-5.4-class model for high-volume coding, tool use, and multimodal tasks",
        "display_order": -4,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.4-nano": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.4 Nano",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high"],
                "default": "low",
            },
        },
        "context_window": 400000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.4-nano",
        "description": "Lowest-cost GPT-5.4-class model for classification, extraction, ranking, and lightweight subagents",
        "display_order": -3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.5": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh"],
                "default": "medium",
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.5",
        "description": "Latest GPT model with expanded context and selectable reasoning effort",
        "display_order": -2,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.5-pro": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.5 Pro",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh"],
                "default": "high",
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "openrouter_id": "openai/gpt-5.5-pro",
        "description": "Higher-latency GPT-5.5 tier for the most demanding reasoning and coding work",
        "display_order": -1,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-6 models (current generation). Sampling parameters are omitted because
    # LangChain only strips them for gpt-5* model names and Astra rejects them.
    # Ref: https://developers.openai.com/api/docs/guides/latest-model
    # -------------------------------------------------------------------------
    "gpt-6-astra": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-6 Astra",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p"],
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-6-astra",
        "description": "OpenAI's most capable model for the hardest reasoning, coding, research, and agentic work",
        "display_order": -9,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # GPT-6.1 Sol rejects the `none` reasoning effort and needs the Responses API for tool calls.
    "gpt-6.1-sol": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-6.1 Sol",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p"],
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-6.1-sol",
        "description": "Near-Astra performance at a lower cost for complex coding, computer use, and professional work",
        "display_order": -8,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-6-sol": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-6 Sol",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p"],
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-6-sol",
        "description": "Fast GPT-6 model for complex coding and agentic workflows",
        "display_order": -7,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-6-luna": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-6 Luna",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p"],
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-6-luna",
        "description": "Most efficient GPT-6 model for focused, high-volume tasks",
        "display_order": -6,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-5.6 models (previous generation).
    # Ref: https://developers.openai.com/api/docs/guides/latest-model
    # -------------------------------------------------------------------------
    "gpt-5.6-sol": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.6 Sol",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-5.6-sol",
        "description": "Frontier GPT-5.6 model for complex professional reasoning, coding, and agentic work",
        "display_order": -5,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.6-terra": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.6 Terra",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-5.6-terra",
        "description": "Balanced GPT-5.6 model for everyday reasoning, coding, and agentic work",
        "display_order": -4,
        "default_enabled": False,
        "recommended": False,
        "recommended_for_onboarding": True,
        "supports_openrouter_proxy": True,
    },
    "gpt-5.6-luna": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-5.6 Luna",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
            "code_interpreter",
            "file_search",
            "mcp",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["none", "low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
        },
        "context_window": 1050000,
        "max_output_tokens": 128000,
        "api_endpoint": "responses",
        "openrouter_id": "openai/gpt-5.6-luna",
        "description": "Cost-efficient GPT-5.6 model for high-volume reasoning and agentic workloads",
        "display_order": -3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # o-series reasoning models.
    # -------------------------------------------------------------------------
    "o3-mini": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "o3 Mini",
        "capabilities": ["reasoning"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["low", "medium", "high"],
                "default": "medium",
            },
        },
        "context_window": 200000,
        "max_output_tokens": 100000,
        "openrouter_id": "openai/o3-mini",
        "description": "Lightweight reasoning model optimized for speed and cost",
        "display_order": 5,
        "default_enabled": True,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "o1": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "o1",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["low", "medium", "high"],
                "default": "high",
            },
        },
        "context_window": 200000,
        "max_output_tokens": 100000,
        "openrouter_id": "openai/o1",
        "description": "Advanced reasoning model for complex problem solving",
        "display_order": 6,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "o4-mini": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "o4 Mini",
        "capabilities": ["reasoning"],
        "features": [
            "reasoning_effort",
            "function_calling",
            "streaming",
            "structured_outputs",
            "web_search",
        ],
        "feature_config": {
            "reasoning_effort": {
                "levels": ["low", "medium", "high"],
                "default": "medium",
            },
        },
        "context_window": 200000,
        "max_output_tokens": 100000,
        "openrouter_id": "openai/o4-mini",
        "description": "Lightweight reasoning model with web search capabilities",
        "display_order": 7,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-4.1 models (coding-focused).
    # -------------------------------------------------------------------------
    "gpt-4.1": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4.1",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1047576,
        "max_output_tokens": 32768,
        "openrouter_id": "openai/gpt-4.1",
        "description": "GPT-4.1 with 1M context window for long documents",
        "display_order": 10,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-4.1-2025-04-14": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4.1 (April 2025)",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1047576,
        "max_output_tokens": 32768,
        "openrouter_id": "openai/gpt-4.1-2025-04-14",
        "description": "GPT-4.1 dated snapshot for reproducibility",
        "display_order": 11,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-4.1-mini": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4.1 Mini",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1047576,
        "max_output_tokens": 32768,
        "openrouter_id": "openai/gpt-4.1-mini",
        "description": "Compact GPT-4.1 for cost-effective long context tasks",
        "display_order": 12,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-4.1-nano": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4.1 Nano",
        "capabilities": ["reasoning"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1047576,
        "max_output_tokens": 32768,
        "openrouter_id": "openai/gpt-4.1-nano",
        "description": "Ultra-compact GPT-4.1 for simple tasks",
        "display_order": 13,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-4o models (multimodal).
    # -------------------------------------------------------------------------
    "gpt-4o": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4o",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 128000,
        "max_output_tokens": 16384,
        "openrouter_id": "openai/gpt-4o",
        "description": "Multimodal GPT-4o for text and vision tasks",
        "display_order": 20,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gpt-4o-mini": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4o Mini",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "api_key_validation",  # Used for OpenAI API key validation.
        ],
        "context_window": 128000,
        "max_output_tokens": 16384,
        "openrouter_id": "openai/gpt-4o-mini",
        "description": "Fast and affordable multimodal model",
        "display_order": 21,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # GPT-4 models (legacy).
    # -------------------------------------------------------------------------
    "gpt-4-turbo": {
        "handler": "openai_api",
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4 Turbo",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
        ],
        "context_window": 128000,
        "max_output_tokens": 4096,
        "openrouter_id": "openai/gpt-4-turbo",
        "description": "Fast GPT-4 with vision capabilities",
        "display_order": 30,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # =========================================================================
    # GOOGLE GEMINI MODELS
    # =========================================================================
    # -------------------------------------------------------------------------
    # Gemini 3.x models (latest generation).
    # -------------------------------------------------------------------------
    "gemini-3.1-pro-preview": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.1 Pro Preview",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.1-pro-preview",
        "description": "Advanced intelligence with complex problem-solving and agentic capabilities",
        "display_order": 0,
        "default_enabled": True,
        "recommended": True,
        "recommended_reason": "Google's most capable reasoning model",
        "supports_openrouter_proxy": True,
    },
    # Gemini 3.6+ Flash: Google recommends leaving sampling at defaults on Gemini 3 (lower
    # temperatures can cause looping) and 3.7/3.8 reject the `minimal` thinking level.
    "gemini-3.8-flash": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.8 Flash",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "thinking",
        ],
        "feature_config": {
            "thinking": {
                "levels": ["low", "medium", "high"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.8-flash",
        "description": "Google's most intelligent Flash model for long-horizon coding, agents, and complex workflows",
        "display_order": -5,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gemini-3.7-flash": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.7 Flash",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "thinking",
        ],
        "feature_config": {
            "thinking": {
                "levels": ["low", "medium", "high"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.7-flash",
        "description": "Gemini 3.7 Flash for general agentic workflows, multi-step orchestration, and coding",
        "display_order": -4,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gemini-3.6-flash": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.6 Flash",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "thinking",
        ],
        "feature_config": {
            "thinking": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.6-flash",
        "description": "Fast, lower-cost Gemini Flash model for code generation and rapid agentic loops",
        "display_order": -3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gemini-3.5-flash-lite": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.5 Flash-Lite",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "thinking",
        ],
        "feature_config": {
            "thinking": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "medium",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.5-flash-lite",
        "description": "Low-latency, cost-effective Gemini model for high-volume subagent tasks and document parsing",
        "display_order": -2,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gemini-3.5-flash": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.5 Flash",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "thinking",
        ],
        "feature_config": {
            "thinking": {
                "default": "auto",
                "supported_modes": ["auto", "none"],
            },
        },
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.5-flash",
        "description": "Latest Gemini Flash model with long context and low-latency reasoning support",
        "display_order": -1,
        "default_enabled": False,
        "recommended": False,
        "recommended_for_onboarding": True,
        "supports_openrouter_proxy": True,
    },
    "gemini-3.1-flash-lite": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3.1 Flash-Lite",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
            "thinking",
        ],
        "feature_config": {
            "thinking": {
                "levels": ["minimal", "low", "medium", "high"],
                "default": "minimal",
            },
        },
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-3.1-flash-lite",
        "description": "Most cost-efficient Gemini 3.1 model for high-volume multimodal and structured-output workloads",
        "display_order": 1,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gemini-3-flash": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 3 Flash",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1000000,
        "max_output_tokens": 8192,
        "openrouter_id": "google/gemini-3-flash",
        "description": "Frontier-class performance at a fraction of the cost",
        "display_order": 1,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # Gemini 2.5 models (stable generation).
    # -------------------------------------------------------------------------
    "gemini-2.5-pro": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 2.5 Pro",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "structured_outputs",
        ],
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "openrouter_id": "google/gemini-2.5-pro",
        "description": "Stable Gemini 2.5 with improved reasoning",
        "display_order": 2,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "gemini-2.5-flash": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 2.5 Flash",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "api_key_validation",  # Used for Google API key validation.
        ],
        "context_window": 1048576,
        "max_output_tokens": 65535,
        "openrouter_id": "google/gemini-2.5-flash",
        "description": "Fast and cost-effective Gemini model",
        "display_order": 3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # =========================================================================
    # ANTHROPIC MODELS
    # =========================================================================
    # -------------------------------------------------------------------------
    # Claude Opus 5.5 / Fable 5.1 / Opus 5 - Latest Anthropic models.
    # Opus 5.5 and Fable 5.1 keep adaptive thinking always on and reject
    # `thinking.type` "disabled"/"enabled" plus forced `tool_choice` (any/tool).
    # Ref: https://platform.claude.com/docs/en/about-claude/models/overview
    # -------------------------------------------------------------------------
    "claude-sonnet-5-5": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Sonnet 5.5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "web_search",
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-sonnet-5.5",
        "description": "Latest Claude Sonnet model for coding, agent workflows, and everyday knowledge work",
        "display_order": -9,
        "default_enabled": True,
        "recommended": True,
        "recommended_reason": "Recommended for standard use",
        "recommended_for_onboarding": True,
        "used_by_setup_agent": True,
        "supports_openrouter_proxy": True,
    },
    "claude-opus-5-5": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Opus 5.5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh", "max"],
                "default_effort": "medium",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-opus-5.5",
        "description": "Anthropic's recommended starting model for long-running agentic coding and knowledge work",
        "display_order": -8,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-fable-5-1": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Fable 5.1",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-fable-5.1",
        "description": "Anthropic's most capable model for demanding reasoning and long-horizon agentic work",
        "display_order": -7,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-opus-5": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Opus 5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-opus-5",
        "description": "Previous Opus-tier Claude model with 1M context, 128K output, and adaptive thinking",
        "display_order": -6,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-fable-5": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Fable 5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-fable-5",
        "description": "Anthropic's most capable generally available model for long-horizon autonomous coding and knowledge work",
        "display_order": -4,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-sonnet-5": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Sonnet 5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "web_search",
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-sonnet-5",
        "description": "Fast, capable Claude Sonnet model for coding, agent workflows, and knowledge work",
        "display_order": -5,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-opus-4-8": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Opus 4.8",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-opus-4.8",
        "description": "Latest Opus-tier Claude model with 1M context, 128K output, and adaptive thinking for advanced agentic work",
        "display_order": -3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-opus-4-7": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Opus 4.7",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high", "xhigh", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-opus-4.7",
        "description": "Latest Claude Opus model with 1M context and 128K output for advanced agentic work",
        "display_order": -2,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-opus-4-6": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Opus 4.6",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",  # New in 4.6: replaces budget_tokens
            "function_calling",
            "streaming",
            "system_prompts",
            "compaction",  # New: server-side context summarization (beta)
            "fast_mode",  # New: 2.5x faster output (research preview)
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",  # Recommended mode for Opus 4.6
                "effort_levels": ["low", "medium", "high", "max"],
                "default_effort": "high",
                # Request provider summaries for Basil's reasoning UI; empty signed adaptive-thinking blocks remain valid and adapter-normalized.
                "default_display": "summarized",
            },
            "fast_mode": {
                "beta_header": "fast-mode-2026-02-01",
                "speed_multiplier": 2.5,
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-opus-4.6",
        "description": "Opus-tier Claude model for building agents and coding with adaptive thinking and 128K output",
        "display_order": 0,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    "claude-sonnet-4-6": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Sonnet 4.6",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "web_search",
            "extended_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "extended_thinking": {
                "budget_tokens": 64000,
                "max_output_tokens_with_thinking": 64000,
            }
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-sonnet-4.6",
        "description": "Latest Claude Sonnet model with expanded context for coding and agent workflows",
        "display_order": -1,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # Claude Opus 4.5 - Previous flagship (November 2025).
    # -------------------------------------------------------------------------
    "claude-opus-4-5-20251101": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude 4.5 Opus",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "extended_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "extended_thinking": {
                "budget": 100000,
                "max_output_tokens_with_thinking": 128000,
            }
        },
        "context_window": 200000,
        "max_output_tokens": 64000,
        "openrouter_id": "anthropic/claude-opus-4.5",
        "description": "Most powerful Claude model with superior reasoning, extended context, and advanced capabilities",
        "display_order": 1,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # MIGRATED MODEL: Claude Sonnet 4.5 (previously in claude_model.py).
    # -------------------------------------------------------------------------
    "claude-sonnet-4-5-20250929": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Sonnet 4.5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "web_search",
            "extended_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
        ],
        "feature_config": {
            "extended_thinking": {
                "budget": 40000,
                "max_output_tokens_with_thinking": 64000,
            }
        },
        "context_window": 200000,
        "max_output_tokens": 64000,
        "openrouter_id": "anthropic/claude-sonnet-4.5",
        "description": "Latest Claude Sonnet with exceptional coding and agent capabilities, can operate autonomously for extended periods",
        "display_order": 2,
        "default_enabled": True,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
    # -------------------------------------------------------------------------
    # Claude Haiku 4.5 - Fast and cost-efficient.
    # -------------------------------------------------------------------------
    "claude-haiku-4-5-20251001": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Haiku 4.5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "function_calling",
            "streaming",
            "system_prompts",
            "api_key_validation",  # Used for Anthropic API key validation.
        ],
        "context_window": 200000,
        "max_output_tokens": 64000,
        "openrouter_id": "anthropic/claude-haiku-4.5",
        "description": "Fast and cost-efficient Claude model for high-volume tasks",
        "display_order": 3,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
}
