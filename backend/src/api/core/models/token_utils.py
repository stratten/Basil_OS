"""Utilities for token counting and context window management."""

import logging
import os
import re
from typing import Dict, List, Optional, Any, Union
from pathlib import Path

logger = logging.getLogger(__name__)

def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text using a simple character-based heuristic.
    
    This is a fallback method when a proper tokenizer is not available.
    
    Args:
        text: The text to estimate tokens for
        
    Returns:
        Estimated token count
    """
    # Simple heuristic: ~4 characters per token for English text
    return len(text) // 4

def detect_context_window(model_path: Path) -> Optional[int]:
    """Try to detect the context window size from the model path or metadata.
    
    Args:
        model_path: Path to the model file
        
    Returns:
        Detected context window size or None if not detected
    """
    # Try to extract from filename
    filename = model_path.name.lower()
    
    # Look for common patterns like "8k", "32k", etc.
    context_patterns = [
        r'(\d+)k',  # e.g., "8k"
        r'context[_-]?(\d+)',  # e.g., "context8192"
        r'ctx[_-]?(\d+)',  # e.g., "ctx4096"
    ]
    
    for pattern in context_patterns:
        match = re.search(pattern, filename)
        if match:
            size = match.group(1)
            try:
                if 'k' in pattern:
                    # Convert from K to actual size (e.g., 8k -> 8192)
                    return int(size) * 1024
                else:
                    return int(size)
            except ValueError:
                pass
    
    # Check for known model identifiers
    known_contexts = {
        'solar-10.7b-instruct-v1.0': 4096,
        'solar-10.7b-v1.0': 4096,
        'qwen3-4b': 32768,
        'qwen3-4b-instruct': 32768,
        'mistral-7b-instruct-v0.2': 8192,
        'llama-2-7b-chat': 4096,
        'llama-2-13b-chat': 4096,
        'llama-2-70b-chat': 4096,
        'phi-2': 2048,
        'phi-3-mini': 8192,
        'phi-3-small': 8192,
        'phi-3-medium': 8192,
    }
    
    for model_id, context_size in known_contexts.items():
        if model_id in filename:
            return context_size
    
    # Default fallback values based on model size indicators
    if '70b' in filename:
        return 4096
    elif '13b' in filename:
        return 4096
    elif '7b' in filename:
        return 4096
    
    # Could not detect
    return None

def count_tokens_with_tokenizer(text: str, tokenizer) -> int:
    """Count tokens in a text using a tokenizer.
    
    Args:
        text: The text to count tokens for
        tokenizer: The tokenizer to use
        
    Returns:
        Token count
    """
    try:
        tokens = tokenizer.encode(text)
        return len(tokens)
    except Exception as e:
        logger.warning(f"Error counting tokens with tokenizer: {e}")
        # Fall back to estimation
        return estimate_tokens(text)

def count_conversation_tokens(messages: List[Dict[str, str]], tokenizer=None) -> int:
    """Count tokens in a conversation.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content' keys
        tokenizer: Optional tokenizer to use for accurate counting
        
    Returns:
        Total token count
    """
    total_tokens = 0
    
    for message in messages:
        content = message.get("content", "")
        if tokenizer:
            tokens = count_tokens_with_tokenizer(content, tokenizer)
        else:
            tokens = estimate_tokens(content)
        total_tokens += tokens
        
        # Add overhead for message formatting (role, template, etc.)
        # This is a rough estimate and varies by model
        total_tokens += 4
    
    # Add overhead for the overall conversation format
    total_tokens += 10
    
    return total_tokens

def truncate_conversation_to_fit(
    messages: List[Dict[str, str]], 
    max_tokens: int, 
    tokenizer=None,
    reserve_tokens: int = 0
) -> List[Dict[str, str]]:
    """Truncate a conversation to fit within a token limit.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content' keys
        max_tokens: Maximum number of tokens allowed
        tokenizer: Optional tokenizer to use for accurate counting
        reserve_tokens: Number of tokens to reserve for the response
        
    Returns:
        Truncated list of messages
    """
    # Adjust max tokens to reserve space for response
    adjusted_max = max_tokens - reserve_tokens
    
    # Always include system messages
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    
    # Count tokens in system messages
    system_tokens = 0
    for msg in system_messages:
        if tokenizer:
            tokens = count_tokens_with_tokenizer(msg.get("content", ""), tokenizer)
        else:
            tokens = estimate_tokens(msg.get("content", ""))
        system_tokens += tokens + 4  # Add message overhead
    
    # If system messages already exceed the limit, truncate them
    if system_tokens > adjusted_max:
        logger.warning(f"System messages exceed token limit ({system_tokens} > {adjusted_max})")
        # Keep as many system messages as possible
        result = []
        current_tokens = 0
        for msg in system_messages:
            if tokenizer:
                tokens = count_tokens_with_tokenizer(msg.get("content", ""), tokenizer)
            else:
                tokens = estimate_tokens(msg.get("content", ""))
                
            if current_tokens + tokens + 4 <= adjusted_max:
                result.append(msg)
                current_tokens += tokens + 4
            else:
                break
        return result
    
    # Start with system messages
    result = list(system_messages)
    current_tokens = system_tokens
    
    # Add other messages from newest to oldest
    other_messages = [msg for msg in messages if msg.get("role") != "system"]
    other_messages.reverse()  # Newest first
    
    for msg in other_messages:
        if tokenizer:
            tokens = count_tokens_with_tokenizer(msg.get("content", ""), tokenizer)
        else:
            tokens = estimate_tokens(msg.get("content", ""))
            
        # Check if adding this message would exceed the limit
        if current_tokens + tokens + 4 <= adjusted_max:
            # Insert after system messages but before other included messages
            result.insert(len(system_messages), msg)
            current_tokens += tokens + 4
        else:
            # Can't fit any more messages
            break

    # Dropping every non-system message would send the model an empty prompt, so a single oversize message is shortened instead of discarded.
    if other_messages and len(result) == len(system_messages):
        newest = other_messages[0]
        remaining_tokens = adjusted_max - current_tokens - 4
        shortened = _shorten_message_to_tokens(newest, remaining_tokens, tokenizer)
        if shortened is not None:
            result.append(shortened)

    return result


def _count_message_tokens(content: str, tokenizer=None) -> int:
    if tokenizer:
        return count_tokens_with_tokenizer(content, tokenizer)
    return estimate_tokens(content)


def _shorten_message_to_tokens(
    message: Dict[str, str],
    token_budget: int,
    tokenizer=None,
) -> Optional[Dict[str, str]]:
    """Keep the head and tail of a message so it fits the token budget; None when nothing useful fits."""
    content = message.get("content", "") or ""
    if token_budget < 32 or not content:
        return None
    total_tokens = _count_message_tokens(content, tokenizer)
    if total_tokens <= token_budget:
        return message
    marker = "\n\n[... middle of this message omitted to fit the model's context window ...]\n\n"
    chars_per_token = len(content) / max(1, total_tokens)
    keep_chars = int(token_budget * chars_per_token * 0.9) - len(marker)
    if keep_chars <= 0:
        return None
    head_chars = int(keep_chars * 0.7)
    tail_chars = keep_chars - head_chars
    shortened = content[:head_chars] + marker + (content[-tail_chars:] if tail_chars > 0 else "")
    return {**message, "content": shortened}