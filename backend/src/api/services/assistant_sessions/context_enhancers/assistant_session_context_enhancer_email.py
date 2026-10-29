import re
import logging
import json
from typing import Dict, Any, Optional
from api.core.knowledge.personalization.contact_context import (
    EmailInteractionKind,
    extract_email_participant_context,
)

logger = logging.getLogger(__name__)

class AssistantSessionEmailEnhancer:
    """
    Specialized context enhancer for email-related AssistantSession suggestions.
    Handles email reply detection, signature filtering, and email-specific prompt generation.
    Personalization context is now provided by the orchestrator.
    """
    
    def __init__(self, coordinator=None):
        self.coordinator = coordinator  # Reference to AssistantSessionContextEnhancer for shared methods
        # Email reply detection patterns
        self.reply_indicators = [
            r"Re:\s*",
            r"From:\s*.*\nTo:\s*.*", 
            r"Sent:\s*.*\nTo:\s*.*",
            r"On\s+.*wrote:",
            r"-----Original Message-----",
            r">.*\n>.*\n>"  # Quoted reply text
        ]
        
        # New email composition patterns
        self.compose_indicators = [
            r"To:\s*$",  # Empty To field
            r"Subject:\s*$",  # Empty Subject field
            r"Compose\s*Email",  # UI text
            r"New\s*Message"  # UI text
        ]
        
        # Common signature patterns for filtering
        self.signature_patterns = [
            r"\n\s*Best\s*,?\s*\n\s*\n.*",  # "Best," followed by blank line and signature
            r"\n\s*Best\s*,?\s*\n.*",       # "Best," immediately followed by signature
            r"\n\s*Regards?\s*,?\s*\n\s*\n.*",  # "Regards," with blank line
            r"\n\s*Regards?\s*,?\s*\n.*",       # "Regards," without blank line
            r"\n\s*Sincerely\s*,?\s*\n\s*\n.*", # "Sincerely," with blank line
            r"\n\s*Sincerely\s*,?\s*\n.*",      # "Sincerely," without blank line
            r"\n\s*Thanks?\s*,?\s*\n\s*\n.*",   # "Thanks," with blank line
            r"\n\s*Thanks?\s*,?\s*\n.*",        # "Thanks," without blank line
            r"\n--\s*\n.*",  # Standard signature delimiter
            r"\n.*\d{3}-\d{3}-\d{4}.*",  # Lines with phone numbers
            r"\n.*www\.\w+\.\w+.*"  # Lines with websites
        ]



    async def enhance(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhance email-specific AssistantSession suggestions with personalization support.
        
        Args:
            content: Raw OCR text from email interface
            instruction: User's voice instruction
            personalization_context: Pre-fetched personalization context from orchestrator
            
        Returns:
            Enhancement result with email-specific processing and personalization
        """
        try:
            # Determine email context type
            if self._is_email_reply(content):
                return await self._enhance_email_reply(content, instruction, personalization_context)
            elif self._is_email_compose(content):
                return await self._enhance_email_compose(content, instruction, personalization_context)
            else:
                # Generic email context
                return await self._enhance_generic_email(content, instruction, personalization_context)
                
        except Exception as e:
            logger.error(f"Error in email enhancement: {e}")
            return {
                "context_type": "email_generic",
                "filtered_content": content,
                "enhanced_prompt": self._build_fallback_prompt(content, instruction),
                "metadata": {"error": str(e), "enhancer": "email"}
            }



    def _is_email_reply(self, content: str) -> bool:
        """Check if content appears to be an email reply."""
        return any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                  for pattern in self.reply_indicators)

    def _is_email_compose(self, content: str) -> bool:
        """Check if content appears to be new email composition."""
        if any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
               for pattern in self.compose_indicators):
            return True
        return (
            re.search(r"^\s*To:\s*[^\n]+", content, re.IGNORECASE | re.MULTILINE) is not None
            and re.search(r"^\s*From:\s*[^\n]+", content, re.IGNORECASE | re.MULTILINE) is None
        )

    async def _enhance_email_reply(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle email reply enhancement with personalization."""
        # Filter out signatures and redundant content
        filtered_content = self._filter_email_signatures(content)
        
        # Extract metadata
        metadata = self._extract_email_metadata(content, EmailInteractionKind.REPLY)
        metadata["enhancer"] = "email"
        metadata["email_type"] = "reply"
        
        # Build reply-specific prompt with personalization
        enhanced_prompt = self._build_email_reply_prompt(
            filtered_content, 
            instruction,
            personalization_context
        )
        
        return {
            "context_type": "email_reply",
            "filtered_content": filtered_content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata,
            "personalization_applied": personalization_context is not None
        }

    async def _enhance_email_compose(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle new email composition enhancement with personalization."""
        # Filter out signatures for compose emails too
        filtered_content = self._filter_email_signatures(content)
        
        metadata = self._extract_email_metadata(content, EmailInteractionKind.COMPOSE)
        metadata["enhancer"] = "email"
        metadata["email_type"] = "compose"
        
        enhanced_prompt = self._build_email_compose_prompt(
            filtered_content, 
            instruction,
            personalization_context
        )
        
        return {
            "context_type": "email_compose",
            "filtered_content": filtered_content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata,
            "personalization_applied": personalization_context is not None
        }

    async def _enhance_generic_email(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle generic email enhancement with personalization."""
        # Filter out signatures for generic emails too
        filtered_content = self._filter_email_signatures(content)
        
        metadata = self._extract_email_metadata(content, EmailInteractionKind.GENERIC)
        metadata["enhancer"] = "email"
        metadata["email_type"] = "generic"
        
        enhanced_prompt = self._build_generic_email_prompt(
            filtered_content, 
            instruction,
            personalization_context
        )
        
        return {
            "context_type": "email_generic",
            "filtered_content": filtered_content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata,
            "personalization_applied": personalization_context is not None
        }

    def _filter_email_signatures(self, content: str) -> str:
        """Remove common signature patterns from email content."""
        filtered = content
        
        for pattern in self.signature_patterns:
            filtered = re.sub(pattern, "", filtered, flags=re.IGNORECASE | re.MULTILINE)
        
        return filtered.strip()

    def _extract_email_metadata(
        self,
        content: str,
        interaction_kind: EmailInteractionKind = EmailInteractionKind.GENERIC,
    ) -> Dict[str, Any]:
        """Extract email metadata for context."""
        participant_context = extract_email_participant_context(content, interaction_kind)
        return participant_context.to_metadata()

    def _build_email_reply_prompt(
        self, 
        content: str, 
        instruction: str,
        personalization: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build prompt optimized for email replies with optional personalization."""
        base_prompt = f"""You are a skilled email ghostwriter who excels at mimicking someone's authentic communication style and voice. Your specialty is writing email replies that sound exactly like the person wrote them - recipients would never suspect otherwise.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural email voice and communication style
- Capture their unique way of expressing themselves, tone, and personality in professional communication
- Sound like a real person writing a genuine email, not AI-generated content
- Avoid corporate email templates or generic business language unless that matches their natural style
- Be concise and clear while maintaining the person's authentic style and voice

COMMUNICATION STYLE ADAPTATION:
- Analyze the email thread and context to understand the relationship and communication style needed
- Match the formality level and relationship dynamic shown in the email thread
- Assess the recipient's likely background and adapt technical depth accordingly
- Use their natural greeting and closing patterns based on the relationship context
- Maintain their authentic voice while being appropriately professional

CONTEXTUAL TECHNICAL COMMUNICATION:
- Analyze the recipient and context to determine appropriate technical depth
- If replying in a technical context: maintain appropriate technical language while ensuring clarity
- If the context suggests a non-technical recipient: use clear analogies and everyday explanations
- Connect technical concepts to assistant_session experiences relevant to the recipient's apparent background
- Make expertise accessible while maintaining the person's natural teaching style

EMAIL REPLY REQUIREMENTS:
- This is a REPLY to an existing email - do NOT include subject lines
- ABSOLUTELY DO NOT include any signatures, sign-offs, closings, or contact information  
- NEVER add "Best,", "Regards,", "Thanks,", "Sincerely," or any other closing
- NEVER sign the email with any name whatsoever
- Do NOT include signatures unless specifically requested
- If the draft seems to already contains a signature that is not directly tied to the body of a previous email, do NOT add it again. Err on the side of not adding it, as most modern email clients will automatically add a signature to the end of the email.
- Focus only on the reply content requested by the user
- Do not repeat information already in the email thread
- END your response with the last word of the actual message content - do NOT add any closing

CRITICAL INSTRUCTION: Ignore any instinct to add polite closings, signatures, or sign-offs. Modern email clients handle signatures automatically. Your job is ONLY to write the message content and STOP. Do not add "Best,", "Thanks,", "Regards," or any name at the end.

CRITICAL: OUTPUT ONLY THE EMAIL REPLY CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about communication style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain way unless explicitly requested by the user
- Do NOT include phrases like "Based on the email thread" or "Looking at the communication style" unless explicitly requested by the user
- Do NOT provide commentary about the person's voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual email reply content
- The first word of your response should be the beginning of the email reply itself
"""
        
        # Add personalization section if available
        if personalization:
            base_prompt += self._build_personalization_section(personalization)
        
        # Add email content and instruction
        base_prompt += f"""
EXISTING EMAIL CONTENT:
{content}

USER INSTRUCTION: {instruction}

EMAIL REPLY CONTENT:"""
        
        return base_prompt

    def _build_email_compose_prompt(
        self, 
        content: str, 
        instruction: str,
        personalization: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build prompt optimized for composing new emails with optional personalization."""
        base_prompt = f"""You are an expert email ghostwriter who specializes in composing emails that perfectly capture someone's authentic voice and communication style. Your expertise is creating emails that sound exactly like the person wrote them.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural email voice, tone, and communication patterns
- Capture their unique way of structuring thoughts and expressing ideas in email
- Sound like genuine personal communication, not automated or template-based content
- Avoid generic business email language unless that naturally matches their style
- Be concise and clear while maintaining the person's authentic style and voice

COMMUNICATION EFFECTIVENESS:
- Analyze the context and intended recipient to determine appropriate communication style
- Adapt tone and formality to the relationship with the recipient based on available context
- Assess the likely audience background and adjust technical complexity accordingly
- If communicating in a technical context: maintain appropriate technical depth while ensuring accessibility
- If the context suggests a broader audience: use clear language and relatable analogies
- Use natural language that makes expertise accessible while maintaining authenticity

EMAIL COMPOSITION GUIDANCE:
- Include subject line if requested by the user
- Match the appropriate level of formality for the relationship and context
- Include signature only if specifically requested
- If the draft seems to already contains a signature that is not directly tied to the body of a previous email, do NOT add it again. Err on the side of not adding it, as most modern email clients will automatically add a signature to the end of the email.
- Be clear, concise, and actionable while maintaining authenticity
- Structure the email in their natural communication style

CRITICAL INSTRUCTION: Ignore any instinct to add polite closings, signatures, or sign-offs. Modern email clients handle signatures automatically. Your job is ONLY to write the message content and STOP. Do not add "Best,", "Thanks,", "Regards," or any name at the end.

CRITICAL: OUTPUT ONLY THE EMAIL CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about communication style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain way unless explicitly requested by the user
- Do NOT include phrases like "Based on the context" or "Looking at the communication style" unless explicitly requested by the user
- Do NOT provide commentary about the person's voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual email content
- The first word of your response should be the beginning of the email itself
"""
        
        # Add personalization section if available
        if personalization:
            base_prompt += self._build_personalization_section(personalization)
        
        # Add context and instruction
        base_prompt += f"""
CONTEXT:
{content}

USER INSTRUCTION: {instruction}

EMAIL CONTENT:"""
        
        return base_prompt

    def _build_generic_email_prompt(
        self, 
        content: str, 
        instruction: str,
        personalization: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build prompt for generic email contexts with optional personalization."""
        base_prompt = f"""You are a skilled email ghostwriter who excels at creating authentic email communication that perfectly captures someone's natural voice and style.

EMAIL REQUIREMENTS:
- NEVER include subject lines unless explicitly requested by the user
- NEVER include signatures or contact information unless explicitly requested by the user
- If the draft already contains a signature, do NOT add it again
- Write ONLY the email body content
- Start directly with the greeting or first line of the email body
- Focus on the message content, not email headers or metadata

CORE GHOSTWRITING PRINCIPLES:
- Write with authentic voice - mirror their natural way of communicating via email
- Capture their unique communication style, tone, and personality
- Sound like genuine personal communication rather than AI-generated content
- Adapt to the appropriate level of formality while maintaining authenticity
- Be concise and clear while maintaining the person's authentic style and voice

CONTEXTUAL COMMUNICATION:
- Analyze the available context to understand the likely audience and communication needs
- If the context suggests technical discussion: maintain appropriate technical depth
- If the context suggests broader audience: use clear, accessible language with relatable examples
- Adapt complexity and terminology to what seems most appropriate for the situation
- Make expertise accessible while maintaining the person's authentic communication style

CRITICAL INSTRUCTION: Ignore any instinct to add polite closings, signatures, or sign-offs. Modern email clients handle signatures automatically. Your job is ONLY to write the message content and STOP. Do not add "Best,", "Thanks,", "Regards," or any name at the end.

EMAIL COMMUNICATION APPROACH:
- Use clear, professional language that matches their natural style
- Structure the email logically while maintaining their authentic voice
- Be concise and actionable while preserving their personality
- Adapt tone appropriately for the context while staying true to their natural style

CRITICAL: OUTPUT ONLY THE EMAIL BODY CONTENT
- Do NOT include subject lines, headers, or signatures unless explicitly requested
- Do NOT include any meta-commentary about communication style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain way unless explicitly requested by the user
- Do NOT include phrases like "Based on the context" or "Looking at the communication style" unless explicitly requested by the user
- Do NOT provide commentary about the person's voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual email body content (greeting or first line)
"""
        
        # Add personalization section if available
        if personalization:
            base_prompt += self._build_personalization_section(personalization)
        
        # Add context and instruction
        base_prompt += f"""
CONTEXT:
{content}

USER INSTRUCTION: {instruction}

EMAIL BODY CONTENT:"""
        
        return base_prompt

    def _build_fallback_prompt(self, content: str, instruction: str) -> str:
        """Build fallback prompt when enhancement fails."""
        return f"""You are an AI assistant helping with an email task.

CONTENT:
{content}

USER INSTRUCTION: {instruction}

Response:"""

    def _build_personalization_section(self, personalization: Dict[str, Any]) -> str:
        """
        Build personalization section - delegates to coordinator's shared implementation.
        
        Args:
            personalization: Context dict from PersonalizationService
            
        Returns:
            Formatted personalization section for prompt
        """
        if self.coordinator:
            return self.coordinator.build_personalization_section(personalization)
        
        # Fallback if no coordinator (shouldn't happen in normal operation)
        logger.warning("No coordinator available for personalization section building")
        return "" 