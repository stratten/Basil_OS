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
    # Removed GPT-5, GPT-5 Mini, GPT-5 Nano, GPT-5.1, and GPT-5.4 Nano, kept as a record so they are not re-added by mistake. OpenAI retires the GPT-5 family snapshots on 2026-12-11 and GPT-5.1 and GPT-5.4 Nano on 2027-04-01 (published replacements GPT-5.6 Sol, Terra, and Luna, and GPT-6 Sol and Luna). By owner decision no saved-preference migration exists for them because no other user ever selected them.
    # -------------------------------------------------------------------------
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
            "api_key_validation",  # Used for OpenAI API key validation.
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
        "default_enabled": True,
        "recommended": True,
        "recommended_reason": "OpenAI's balanced model for most tasks",
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
    # Removed OpenAI models, kept as a record so they are not re-added by mistake. OpenAI shuts down o1, o3-mini, o4-mini, GPT-4.1 Nano, and GPT-4 Turbo on 2026-10-23, and GPT-4o, GPT-4o Mini, GPT-4.1, and GPT-4.1 Mini on 2027-01-14 (OpenRouter follows the same date). Saved preferences move to a replacement through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # Removed GPT-5.5 and GPT-5.5 Pro by owner decision (superseded by GPT-5.6 and GPT-6; OpenAI retired GPT-5.5 from ChatGPT and Codex on 2026-10-14 and has announced no API shutdown date). Saved preferences move to gpt-5.6-terra and gpt-5.6-sol through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # Removed GPT-5.2 and GPT-5.2 Pro by owner decision (superseded by GPT-5.6 and GPT-6). Saved preferences move to gpt-5.6-terra and gpt-5.6-sol through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py. GPT-5.4 Mini stays because no newer mini exists.
    # -------------------------------------------------------------------------
    # =========================================================================
    # GOOGLE GEMINI MODELS
    # =========================================================================
    # -------------------------------------------------------------------------
    # Gemini 3.x models (latest generation).
    # -------------------------------------------------------------------------
    # Gemini 4 Argon: thinking_level replaces thinking_budget, sampling parameters are ignored, and explicit context caching is unsupported. Google recommends at least 32,768 max output tokens because thinking shares the limit. Not available on the Gemini API free tier.
    "gemini-4-argon": {
        "handler": "gemini_api",
        "location": "cloud",
        "provider": PROVIDER_GOOGLE,
        "display_name": "Gemini 4 Argon",
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
        "max_output_tokens": 32768,
        "openrouter_id": "google/gemini-4-argon",
        "description": "Google's most capable model for hard software engineering, math and science, and long-running agent work",
        "display_order": -6,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
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
        "recommended_reason": "Google's capable Pro-tier reasoning model with a 1M-token context window",
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
        "recommended_for_onboarding": True,
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
            "api_key_validation",  # Used for Google API key validation.
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
    # -------------------------------------------------------------------------
    # Removed gemini-3.5-flash and gemini-3.7-flash, which are aliases Google now routes to Gemini 3.6 Flash and Gemini 3.8 Flash, and gemini-3.1-flash-lite, which Google shuts down on 2027-05-07 (replacement gemini-3.5-flash-lite). Saved preferences move to gemini-3.6-flash, gemini-3.8-flash, and gemini-3.5-flash-lite through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # Removed Gemini models, kept as a record so they are not re-added by mistake. gemini-3-flash was never a valid OpenRouter or Google model id (Google's is gemini-3-flash-preview), and OpenRouter expires gemini-2.5-pro and gemini-2.5-flash on 2026-10-20 while Google limits them to existing users. Saved preferences move to a replacement through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # -------------------------------------------------------------------------
    # =========================================================================
    # ANTHROPIC MODELS
    # =========================================================================
    # -------------------------------------------------------------------------
    # Claude Opus 5.5 / Fable 5.1 - Latest Anthropic models.
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
    # -------------------------------------------------------------------------
    # Removed Claude Sonnet 4.5 (claude-sonnet-4-5-20250929), kept as a record so it is not re-added by mistake. Anthropic deprecated it and retires it on 2026-11-30 (recommended replacement claude-sonnet-5-5). Saved preferences move to the replacement through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # Removed Claude Fable 5 and Claude Sonnet 5 by owner decision (Anthropic lists both as active legacy models with retirement not sooner than 2027-06-09 and 2027-06-30; Fable 5.1 and Sonnet 5.5 supersede them). Saved preferences move to claude-fable-5-1 and claude-sonnet-5-5 through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # Removed Claude Opus 4.5, 4.6, 4.7, 4.8, and 5 by owner decision (every Opus generation before 5.5), Claude Haiku 4.5 (Anthropic's earliest retirement date for it was 2026-10-15), and Claude Sonnet 4.6 (removed by owner decision; Anthropic lists it as active with retirement not sooner than 2027-02-17). Haiku 5.5 and Sonnet 5.5 replace them. Saved preferences move to claude-opus-5-5, claude-haiku-5-5, and claude-sonnet-5-5 through RETIRED_CLOUD_MODEL_REPLACEMENTS in preference_models/migrations.py.
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Claude Haiku 5.5 - Fastest and lowest cost (retirement not sooner than 2027-10-07).
    # -------------------------------------------------------------------------
    "claude-haiku-5-5": {
        "handler": "anthropic_api",
        "location": "cloud",
        "provider": PROVIDER_ANTHROPIC,
        "display_name": "Claude Haiku 5.5",
        "capabilities": ["reasoning", "vision"],
        "features": [
            "adaptive_thinking",
            "function_calling",
            "streaming",
            "system_prompts",
            "api_key_validation",  # Used for Anthropic API key validation.
        ],
        "feature_config": {
            "adaptive_thinking": {
                "type": "adaptive",
                "effort_levels": ["low", "medium", "high"],
                "default_effort": "medium",
                "default_display": "summarized",
            },
            "request_parameters": {
                "omit": ["temperature", "top_p", "top_k"],
            },
        },
        "context_window": 1000000,
        "max_output_tokens": 128000,
        "openrouter_id": "anthropic/claude-haiku-5.5",
        "description": "Fastest Claude model for high-volume, latency-sensitive work such as classification, extraction, and routing",
        "display_order": 2,
        "default_enabled": False,
        "recommended": False,
        "supports_openrouter_proxy": True,
    },
}
