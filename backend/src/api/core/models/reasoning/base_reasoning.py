from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Set, List, AsyncGenerator
import asyncio
import inspect
import re

from ..base_model import BaseAIModel, ModelMetadata, ModelState
from ..model_types import ModelCapability, ReasoningCapable
from ..token_utils import truncate_conversation_to_fit, count_conversation_tokens
from .streaming_contract import (
    GenerationBudget,
    StreamEvent,
    resolve_generation_budget,
    terminal_from_error,
    terminal_from_provider_reason,
)

import logging
logger = logging.getLogger(__name__)


class ReasoningTruncatedError(RuntimeError):
    """Generation stopped inside a reasoning block, before any answer was emitted.

    Raised by adapters whose models interleave reasoning with the answer in a
    single text stream (llama.cpp GGUF models such as Qwen and DeepSeek-R1 open a
    <think> block first). Which markers signal reasoning is model-family
    knowledge, so recognizing this belongs in each adapter rather than in
    callers; callers only need to distinguish "the model never answered" from a
    genuine answer they can parse. Cloud reasoning models return reasoning in a
    separate field and so never raise this.
    """


# Output budget for the streaming entry points that take no explicit budget:
# chat_completion_streaming and generate_streaming. It is deliberately larger
# than the non-streaming default because those callers render a whole reply into
# the conversation UI. An adapter overriding _generate_from_messages_streaming
# must apply this same default, or replies truncate earlier than they used to.
DEFAULT_STREAMING_MAX_TOKENS = 4000


def _accepts_keyword(func: Any, name: str) -> bool:
    """Whether func declares a keyword parameter, or takes arbitrary kwargs.

    Adapter generate_response signatures differ - only the llama.cpp adapter
    takes preserve_thinking - so passing it blindly raises TypeError on the
    others, the same failure enable_web_search caused.
    """
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return True
    return name in parameters


def has_unterminated_reasoning(text: str, open_tag: str, close_tag: str) -> bool:
    """True when a reasoning block opened and never closed.

    Adapters supply their own markers because each model family differs; the
    bracket-matching itself is shared so the families that do use inline tags
    cannot drift apart.
    """
    closed_removed = re.sub(
        rf"{re.escape(open_tag)}.*?{re.escape(close_tag)}", "", text, flags=re.DOTALL
    )
    return open_tag in closed_removed


def strip_inline_reasoning(text: str, open_tag: str, close_tag: str) -> str:
    """Drop reasoning blocks, including an unterminated trailing one.

    An unterminated block is cut from its opening tag onward: everything after it
    is reasoning, and returning it would hand raw chain-of-thought to a caller as
    though it were the answer.
    """
    text = re.sub(
        rf"{re.escape(open_tag)}.*?{re.escape(close_tag)}\s*", "", text, flags=re.DOTALL
    )
    if open_tag in text:
        text = text.split(open_tag, 1)[0]
    return text


def _estimate_token_count(text: str) -> int:
    """Cheap fallback estimate for stream metadata when provider usage is absent."""
    return max(0, (len(text or "") + 3) // 4)


class BaseReasoningModel(BaseAIModel, ReasoningCapable, ABC):
    """Base class for all reasoning models."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities | {ModelCapability.REASONING})
        self.max_context_length: int = 2048  # Default, should be overridden
        self.temperature: float = 0.7  # Default temperature for generation
        self.top_p: float = 0.9  # Default top_p for generation

    async def predict(self, input_data: Any) -> Any:
        """Implement BaseAIModel's predict method to handle reasoning requests."""
        if isinstance(input_data, str):
            return await self.generate_response(input_data)
        elif isinstance(input_data, dict):
            if 'prompt' in input_data:
                context = input_data.get('context')
                max_tokens = input_data.get('max_tokens', 2000)
                return await self.generate_response(input_data['prompt'], context, max_tokens)
            elif 'text' in input_data:
                # Treat 'text' as a prompt for generation (legacy compatibility)
                return await self.generate_response(input_data['text'])
        raise ValueError(f"Unsupported input type for reasoning: {type(input_data)}")

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 2000
    ) -> str:
        """Generate a reasoned response to a prompt."""
        pass

    def validate_capabilities(self) -> bool:
        """Validate that this model supports reasoning capabilities."""
        metadata = self.get_metadata()
        return ModelCapability.REASONING in metadata.capabilities

    @abstractmethod
    def validate(self) -> bool:
        """Validate model specific functionality."""
        pass

    def configure(self, **kwargs) -> None:
        """Configure model parameters."""
        if 'temperature' in kwargs:
            self.temperature = float(kwargs['temperature'])
        if 'top_p' in kwargs:
            self.top_p = float(kwargs['top_p'])
        if 'max_context_length' in kwargs:
            self.max_context_length = int(kwargs['max_context_length'])
            
    async def chat_completion(self, messages: List[Dict[str, str]]) -> Dict[str, str]:
        """Convert chat messages to a prompt and generate a response.
        
        This method adapts the chat completion interface expected by ConversationService
        to the generate_response method implemented by reasoning models.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Returns:
            Dictionary with 'content' key containing the generated response
        """
        # Get context size and reserve tokens for response
        context_size = getattr(self, 'n_ctx', getattr(self, 'max_context_length', 2048))
        
        # Adaptive reserve calculation: smaller % for larger contexts
        # Small models (<=8K): Reserve 25% or 1000 tokens
        # Medium models (8K-64K): Reserve 15% or 2000 tokens
        # Large models (64K-200K): Reserve 10% or 4000 tokens
        # Very large models (>200K): Reserve 5% or 8000 tokens
        if context_size <= 8192:
            reserve_tokens = min(1000, context_size // 4)  # 25%
        elif context_size <= 65536:
            reserve_tokens = min(2000, context_size // 7)  # ~15%
        elif context_size <= 200000:
            reserve_tokens = min(4000, context_size // 10)  # 10%
        else:
            reserve_tokens = min(8000, context_size // 20)  # 5%
        
        # Log token usage
        tokenizer = getattr(self, 'tokenizer', None)
        total_tokens = count_conversation_tokens(messages, tokenizer)
        logger.info(f"Chat completion request with {len(messages)} messages, ~{total_tokens} tokens")
        
        # Check if we need to truncate the conversation
        if total_tokens + reserve_tokens > context_size:
            logger.info(f"Truncating conversation to fit context window ({context_size} tokens, reserving {reserve_tokens})")
            truncated_messages = truncate_conversation_to_fit(
                messages, 
                context_size, 
                tokenizer,
                reserve_tokens
            )
            
            # Log truncation details
            original_count = len(messages)
            truncated_count = len(truncated_messages)
            if truncated_count < original_count:
                logger.info(f"Truncated conversation from {original_count} to {truncated_count} messages")
                
                # Check if we have a tokenizer for accurate counts
                if tokenizer:
                    truncated_tokens = count_conversation_tokens(truncated_messages, tokenizer)
                    logger.info(f"Truncated from ~{total_tokens} to ~{truncated_tokens} tokens")
            
            # Use truncated messages
            messages = truncated_messages
        
        # Generate response
        response_text = await self.generate_from_messages(messages)
        
        # Return in the expected format with metadata
        return {
            "content": response_text,
            "metadata": {
                "input_tokens": total_tokens,
                "model": self.__class__.__name__,
                "context_size": context_size
            }
        }
    
    async def generate_from_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False,
        enable_web_search: bool = True,
    ) -> str:
        """Generate from a conversation without forcing it through text.

        The default renders messages to a prompt string, which is what every
        adapter did before this existed. Adapters whose runtime accepts messages
        directly override this, so the conversation is never flattened into text
        and parsed back - a round trip that loses the model's real template.
        """
        prompt = self._format_chat_messages(messages)
        kwargs: Dict[str, Any] = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if preserve_thinking and _accepts_keyword(
            self.generate_response, "preserve_thinking"
        ):
            kwargs["preserve_thinking"] = True
        if not enable_web_search and _accepts_keyword(
            self.generate_response, "enable_web_search"
        ):
            kwargs["enable_web_search"] = False
        return await self.generate_response(prompt, **kwargs)

    async def _generate_from_messages_streaming(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming counterpart to generate_from_messages.

        The default deliberately routes back through _generate_response_streaming
        so adapters that implement real token streaming (Solar, the auth proxy)
        keep it; only adapters that override this stop flattening messages.
        """
        prompt = self._format_chat_messages(messages)
        if max_tokens is None:
            async for token in self._generate_response_streaming(prompt):
                yield token
        else:
            async for token in self._generate_response_streaming(
                prompt, max_tokens=max_tokens
            ):
                yield token

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        budget: Optional[GenerationBudget] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Streaming chat completion that preserves terminal metadata."""
        resolved_budget = budget or resolve_generation_budget(self)
        full_response = ""
        try:
            async for token in self._chat_completion_streaming_with_budget(
                messages,
                resolved_budget,
            ):
                full_response += token
                yield StreamEvent(text=token)
            yield StreamEvent(
                terminal=terminal_from_provider_reason(
                    "completed",
                    output_tokens=_estimate_token_count(full_response),
                )
            )
        except Exception as exc:
            yield StreamEvent(terminal=terminal_from_error(exc))

    async def _chat_completion_streaming_with_budget(
        self,
        messages: List[Dict[str, str]],
        budget: GenerationBudget,
    ) -> AsyncGenerator[str, None]:
        """Default budget-aware token stream used by the event stream contract."""
        context_size = getattr(self, 'n_ctx', getattr(self, 'max_context_length', 2048))
        tokenizer = getattr(self, 'tokenizer', None)
        total_tokens = count_conversation_tokens(messages, tokenizer)
        if budget.input_budget_tokens is not None and total_tokens > budget.input_budget_tokens:
            logger.info(
                "Truncating streaming conversation to fit budget: %s > %s",
                total_tokens,
                budget.input_budget_tokens,
            )
            messages = truncate_conversation_to_fit(
                messages,
                max_tokens=budget.input_budget_tokens,
                tokenizer=tokenizer,
                reserve_tokens=budget.effective_output_tokens,
            )
        elif total_tokens + budget.effective_output_tokens > context_size:
            messages = truncate_conversation_to_fit(
                messages,
                max_tokens=max(1, context_size - budget.effective_output_tokens),
                tokenizer=tokenizer,
                reserve_tokens=budget.effective_output_tokens,
            )

        async for token in self._generate_from_messages_streaming(
            messages,
            max_tokens=budget.effective_output_tokens,
        ):
            yield token

    async def chat_completion_streaming(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Streaming version of chat_completion that yields tokens as they're generated.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Yields:
            Tokens as they are generated, and the final token includes metadata
        """
        # Get context size and reserve tokens for response
        context_size = getattr(self, 'n_ctx', getattr(self, 'max_context_length', 2048))
        
        # Adaptive reserve calculation (same as non-streaming)
        if context_size <= 8192:
            reserve_tokens = min(1000, context_size // 4)  # 25%
        elif context_size <= 65536:
            reserve_tokens = min(2000, context_size // 7)  # ~15%
        elif context_size <= 200000:
            reserve_tokens = min(4000, context_size // 10)  # 10%
        else:
            reserve_tokens = min(8000, context_size // 20)  # 5%
        
        # Log token usage
        tokenizer = getattr(self, 'tokenizer', None)
        total_tokens = count_conversation_tokens(messages, tokenizer)
        logger.info(f"Streaming chat completion request with {len(messages)} messages, ~{total_tokens} tokens")
        
        # Check if we need to truncate the conversation
        if total_tokens + reserve_tokens > context_size:
            logger.info(f"Truncating conversation to fit context window ({context_size} tokens, reserving {reserve_tokens})")
            truncated_messages = truncate_conversation_to_fit(
                messages, 
                context_size, 
                tokenizer,
                reserve_tokens
            )
            
            # Log truncation details
            original_count = len(messages)
            truncated_count = len(truncated_messages)
            if truncated_count < original_count:
                logger.info(f"Truncated conversation from {original_count} to {truncated_count} messages")
                
                # Check if we have a tokenizer for accurate counts
                if tokenizer:
                    truncated_tokens = count_conversation_tokens(truncated_messages, tokenizer)
                    logger.info(f"Truncated from ~{total_tokens} to ~{truncated_tokens} tokens")
            
            # Use truncated messages
            messages = truncated_messages
        
        # Generate response with streaming
        full_response = ""
        async for token in self._generate_from_messages_streaming(messages):
            full_response += token
            yield token
        
        # We can't return a value from an async generator, so we'll just log the metadata
        logger.info(f"Streaming completed. Generated {len(full_response)} characters, input tokens: ~{total_tokens}, model: {self.__class__.__name__}, context_size: {context_size}")
    
    async def generate_streaming(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Generate a response with streaming tokens.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Yields:
            Tokens as they are generated
        """
        # Calculate context size and reserve tokens for response
        context_size = self.max_context_length
        reserve_tokens = min(1000, context_size // 4)  # Reserve 25% of context for response
        
        # Count tokens in the conversation
        total_tokens = count_conversation_tokens(messages, self.tokenizer)
        logger.info(f"Total tokens in conversation: ~{total_tokens}")
        
        # Check if we need to truncate
        if total_tokens + reserve_tokens > context_size:
            logger.warning(f"Conversation exceeds context limit ({total_tokens} + {reserve_tokens} > {context_size})")
            
            # Truncate conversation to fit context
            truncated_messages = truncate_conversation_to_fit(
                messages, 
                max_tokens=context_size - reserve_tokens,
                tokenizer=self.tokenizer,
                reserve_tokens=reserve_tokens
            )
            
            if self.tokenizer:
                # Log token counts if we have a tokenizer
                try:
                    truncated_tokens = count_conversation_tokens(truncated_messages, self.tokenizer)
                    logger.info(f"Truncated from ~{total_tokens} to ~{truncated_tokens} tokens")
                except Exception as e:
                    logger.warning(f"Error counting tokens after truncation: {e}")
            
            # Use truncated messages
            messages = truncated_messages
        
        # Generate response with streaming
        full_response = ""
        async for token in self._generate_from_messages_streaming(messages):
            full_response += token
            yield token
        
        # We can't return a value from an async generator, so we'll just log the metadata
        logger.info(f"Streaming completed. Generated {len(full_response)} characters, input tokens: ~{total_tokens}")
    
    async def _generate_response_streaming(self, prompt: str, max_tokens: int = DEFAULT_STREAMING_MAX_TOKENS) -> AsyncGenerator[str, None]:
        """Generate a response with streaming.
        
        This is a default implementation that subclasses should override for better performance.
        
        Args:
            prompt: The prompt to generate from
            max_tokens: Maximum number of tokens to generate
            
        Yields:
            Tokens as they are generated
        """
        # Default implementation just splits the response into tokens
        # Subclasses should override this with actual streaming implementation
        # Pass preserve_thinking=True to keep <think> tags for conversation UI
        stream_kwargs: Dict[str, Any] = {"max_tokens": max_tokens}
        if _accepts_keyword(self.generate_response, "preserve_thinking"):
            stream_kwargs["preserve_thinking"] = True
        response = await self.generate_response(prompt, **stream_kwargs)
        
        # Simulate streaming by yielding one character at a time
        # This is just a fallback - actual implementations should use proper token streaming
        for char in response:
            yield char
            await asyncio.sleep(0.01)  # Small delay to simulate streaming
    
    def _format_chat_messages(self, messages: List[Dict[str, str]]) -> str:
        """Format chat messages into a prompt string.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Returns:
            Formatted prompt string
        """
        # Check if we have a tokenizer with chat template
        tokenizer = getattr(self, 'tokenizer', None)
        if tokenizer and hasattr(tokenizer, 'apply_chat_template'):
            try:
                # Convert our messages to the format expected by the tokenizer
                formatted_messages = []
                for msg in messages:
                    role = msg.get("role", "").lower()
                    content = msg.get("content", "")
                    
                    # Skip empty messages
                    if not content:
                        continue
                        
                    # Map roles to the expected format
                    if role in ["user", "assistant", "system"]:
                        formatted_messages.append({"role": role, "content": content})
                
                # Use the tokenizer's chat template
                prompt = tokenizer.apply_chat_template(
                    formatted_messages, 
                    tokenize=False,
                    add_generation_prompt=True
                )
                logger.info(f"Using tokenizer chat template for {len(formatted_messages)} messages")
                return prompt
            except Exception as e:
                logger.warning(f"Error using tokenizer chat template: {e}")
                # Fall back to manual formatting
        
        # Manual formatting based on common patterns. Reached when an adapter has
        # no tokenizer exposing a chat template - QwenModel stores its tokenizer
        # as _tokenizer, and DeepSeekModel can install a FallbackTokenizer - so it
        # stays, but it produces a format no instruct model was trained on and
        # should be visible when it happens.
        logger.warning(
            "No chat template available for %s; falling back to generic "
            "User/Assistant formatting",
            self.__class__.__name__,
        )
        formatted_prompt = ""
        
        # Check if this is a SOLAR model
        is_solar = "solar" in self.__class__.__name__.lower()
        
        for message in messages:
            role = message.get("role", "").lower()
            content = message.get("content", "")
            
            if is_solar:
                # SOLAR format
                if role == "user":
                    formatted_prompt += f"### User:\n{content}\n\n"
                elif role == "assistant":
                    formatted_prompt += f"### Assistant:\n{content}\n\n"
                elif role == "system":
                    formatted_prompt += f"### System:\n{content}\n\n"
            else:
                # Generic format
                if role == "user":
                    formatted_prompt += f"User: {content}\n\n"
                elif role == "assistant":
                    formatted_prompt += f"Assistant: {content}\n\n"
                elif role == "system":
                    formatted_prompt += f"System: {content}\n\n"
        
        # Add final assistant prompt
        if is_solar:
            formatted_prompt += "### Assistant:\n"
        else:
            formatted_prompt += "Assistant: "
        
        return formatted_prompt 