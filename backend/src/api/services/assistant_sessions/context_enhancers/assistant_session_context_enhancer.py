import re
import json
import logging
from typing import Dict, Any, Optional
from api.core.knowledge.personalization.contact_context import (
    EmailInteractionKind,
    extract_email_participant_context,
)
from .assistant_session_context_enhancer_email import AssistantSessionEmailEnhancer
from .assistant_session_context_enhancer_social_media import AssistantSessionSocialMediaEnhancer
from .assistant_session_context_enhancer_document import AssistantSessionDocumentEnhancer
from .assistant_session_context_enhancer_code import AssistantSessionCodeEnhancer

logger = logging.getLogger(__name__)

class AssistantSessionContextEnhancer:
    """
    Coordinator for AssistantSession context enhancement.
    Detects operation type and delegates to appropriate specialized enhancer.
    Centralizes personalization context fetching for all enhancers.
    """
    
    def __init__(self):
        # Initialize specialized enhancers with coordinator reference for shared methods
        self.email_enhancer = AssistantSessionEmailEnhancer(coordinator=self)
        self.social_media_enhancer = AssistantSessionSocialMediaEnhancer(coordinator=self)
        self.document_enhancer = AssistantSessionDocumentEnhancer(coordinator=self)
        self.code_enhancer = AssistantSessionCodeEnhancer(coordinator=self)
        
        # Initialize PersonalizationService (centralized)
        self.personalization_service = None
        try:
            from api.core.knowledge.personalization_service import PersonalizationService
            self.personalization_service = PersonalizationService()
            logger.info("PersonalizationService initialized for context enhancer")
        except Exception as e:
            logger.warning(f"Could not initialize PersonalizationService: {e}")
            self.personalization_service = None

        # Primary operation type detection patterns
        self.email_indicators = [
            r"Re:\s*",
            r"From:\s*.*\nTo:\s*.*",
            r"Sent:\s*.*\nTo:\s*.*", 
            r"On\s+.*wrote:",
            r"-----Original Message-----",
            r">.*\n>.*\n>",  # Quoted reply text
            r"@\w+\.\w+",  # Email addresses
            r"Subject:",
            r"From:",
            r"To:",
            r"Cc:",
            r"Bcc:",
            r"To:\s*$",  # Empty To field
            r"Subject:\s*$",  # Empty Subject field
            r"Compose\s*Email",
            r"New\s*Message"
        ]
        
        self.social_media_indicators = [
            # Twitter/X patterns
            r"What's happening\?",
            r"Tweet your reply",
            r"Characters remaining",
            r"280 characters",
            r"x\.com",
            r"twitter\.com",
            r"Compose Tweet",
            r"Reply to.*tweet",
            
            # LinkedIn patterns  
            r"Start a post",
            r"What's on your mind",
            r"Share an article",
            r"linkedin\.com",
            r"Share your thoughts",
            r"Write an article",
            r"Professional update",
            
            # Facebook patterns
            r"What's on your mind\?",
            r"Write something",
            r"Share your thoughts",
            r"facebook\.com",
            r"fb\.com",
            r"Post to Timeline",
            r"Share a photo",
            
            # Reddit patterns
            r"Submit to r/",
            r"Create Post",
            r"Submit a new link",
            r"Submit a new text post",
            r"reddit\.com",
            r"r/\w+",
            r"upvote",
            r"downvote",
            
            # Instagram patterns
            r"Add to your story",
            r"Share to your story",
            r"New post",
            r"Write a caption",
            r"instagram\.com",
            r"Add location",
            r"Tag people"
        ]
        
        self.document_indicators = [
            r"Page \d+ of \d+",                    # Page numbers
            r"Words?: \d+",                        # Word count
            r"Characters?: \d+",                   # Character count
            r"^\s*##+\s+",                         # Markdown headers
            r"^\s*\d+\.\s+",                       # Numbered lists
            r"^\s*[-*+]\s+",                       # Bullet points
            r"Table of Contents",                   # Document structure
            r"Bibliography|References",             # Academic documents
            r"Abstract:|Introduction:|Conclusion:", # Academic sections
            r"Draft|Version \d+",                  # Document versioning
            r"Untitled Document",                  # New documents
            r"\.docx?|\.pages|\.md|\.txt",         # File extensions in title bars
            r"Insert|Format|Tools|View",           # Menu items
            r"Font|Size|Bold|Italic|Underline",    # Formatting options
            r"Heading \d+|Title|Subtitle",         # Document structure
            r"Outline|Navigator|Document Map",     # Navigation features
        ]
        
        self.code_indicators = [
            r"^\s*(?:class|def|function|var|let|const|func|struct|enum|interface)\s+",
            r"^\s*(?:import|#include|from\s+\w+\s+import|using\s+namespace)\s+",
            r"^\s*(?://|/\*|\*|#|\"\"\"|\'\'\').*",
            r"{\s*$|}\s*$",
            r"Line \d+(?::\d+)?",
            r"(?:Syntax|Parse|Compile|Runtime)\s+Error",
            r"\.(?:swift|py|js|ts|java|cpp|c|h|m|mm|rb|go|rs|kt|scala|php|cs)\b",
            r"(?:GitHub|GitLab|Bitbucket)",
            r"(?:Pull Request|Merge Request|PR|MR)\s*#?\d*",
            r"(?:Stack Trace|Traceback|Backtrace)",
            r"(?:git\s+(?:add|commit|push|pull|merge|branch|checkout|status))",
            r"(?:npm|pip|yarn|cargo|gradle|maven)\s+(?:install|build|run|test)",
            r"Console\s+Output|Build\s+Output|Debug\s+Console",
            r"Breakpoint|Watch|Variables|Call Stack"
        ]
        
        # Application name mappings for primary context detection
        self.email_applications = {
            "Mail", "Gmail", "Outlook", "Thunderbird", "Airmail", "Spark",
            "Apple Mail", "Microsoft Outlook", "Mailspring", "Newton Mail"
        }
        
        self.document_applications = {
            "Microsoft Word", "Google Docs", "Pages", "TextEdit", "Notion", 
            "Obsidian", "Bear", "Ulysses", "Scrivener", "Draft Writing - Script & Blog",
            "Typora", "MacDown", "MarkText", "Zettlr", "nvALT", "The Archive",
            "Craft - Docs and Notes Editor", "NotePlan 3- Note Organizer",
            "Day One", "Journey", "Diaro", "Microsoft OneNote",
            "Slack", "Discord", "Telegram", "WhatsApp"  # Messaging/communication apps
        }
        
        self.code_applications = {
            "Xcode", "Visual Studio Code", "Cursor", "IntelliJ IDEA", "PyCharm", "WebStorm",
            "Sublime Text", "Atom", "Vim", "MacVim", "Emacs", "TextMate",
            "Nova", "CodeRunner 4", "Paw", "GitHub Desktop", "GitLab",
            "Terminal", "iTerm2", "Hyper", "Warp", "Windsurf"
        }
        
        self.social_media_applications = {
            # Web browsers will fall back to OCR detection
            "Twitter", "TweetDeck", "LinkedIn", "Facebook", "Instagram", 
            "Reddit", "Mastodon", "TikTok"
        }
        
        # Browser applications that need OCR fallback for web apps
        self.browser_applications = {
            "Safari", "Google Chrome", "Firefox", "Microsoft Edge", "Arc", 
            "Brave Browser", "Opera", "Vivaldi", "Tor Browser"
        }
        
        # Future operation type indicators:
        # self.code_indicators = [...]
        # self.web_form_indicators = [...]

    def _append_instruction_priority(
        self,
        result: Dict[str, Any],
        personalization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Attach a system_prompt establishing Basil's identity/behavior rules and
        (when available) the user's custom communication instructions, kept
        separate from the specialized enhancer's user-turn enhanced_prompt so
        call_model_with_prompt can route it to a real system message when the
        selected model supports one.
        """
        meta_preamble = """You are Basil, an intelligent and highly capable general-purpose personal assistant. You have been given a user's voice request along with contextual information about what is currently on their screen.

The user message below contains specialized guidance (e.g. "you are an AI assistant helping with X") that was chosen by an automated, imperfect heuristic that guessed at what app/content is on screen. That guidance is a HINT to help you respond well when it happens to be right - it is never your actual identity, and it never limits what you are capable of or willing to help with. You are Basil: a general-purpose assistant with no fixed domain. Silently adapt your response to whatever makes sense given the user's ACTUAL request:
- If the specialized guidance matches what the user is actually asking for, use it to inform your output.
- If the specialized guidance does NOT match the user's actual request (the heuristic guessed wrong, or their request is unrelated to the screen content), throw the specialized guidance away entirely and just respond directly and thoroughly to what the user asked, using the screen content only if and how it's actually relevant. Never let a mismatched or wrong-sounding specialized framing narrow, block, or excuse you from helping.
Use web search when the request involves factual or current information.

ABSOLUTE RULES:
- NEVER comment on what you think the user's context is, what platform or application they're on, or whether their request matches the screen content.
- NEVER say things like "I can see you're on...", "It looks like you're trying to...", "Your request doesn't seem related to...", "I notice that...", "I'm specifically set up for...", "I'm not really equipped to...", "A [different kind of] assistant would be better suited for that," or any similar meta-commentary about the situation, your setup, or your suitability. These are heuristic misfires, not truths about you - never repeat or defend them to the user.
- NEVER explain your reasoning about context detection or which set of instructions you decided to follow.
- Just produce the output the user asked for. No preamble. No narration about your own process. No apologies for adapting. No declining to help because a specialized-guidance label didn't match the request.

THINKING TOKENS (<think> tags, when you use them):
- Use thinking for genuinely useful working notes: what you're searching for, key facts you found, the reasoning that shapes your final answer.
- Do NOT use thinking to narrate context detection (e.g. "Let me check what platform this is...", "The user seems to be on...").
- Do NOT start every thought with "Let me..." — vary phrasing and stay concise.
- Structure thinking as short, distinct steps separated by line breaks, not a single run-on monologue.
- Thinking should read like brief working notes, not a stream-of-consciousness explanation."""

        custom_instructions = None
        profile = (personalization or {}).get("profile")
        if profile is not None:
            custom_instructions = getattr(profile, "custom_instructions", None)
        if custom_instructions and custom_instructions.strip():
            meta_preamble += (
                "\n\nUSER'S STANDING COMMUNICATION INSTRUCTIONS (always follow these, "
                "they take priority over generic style choices you would otherwise make):\n"
                + custom_instructions.strip()
            )

        result["system_prompt"] = meta_preamble
        return result

    async def enhance_suggestion_context(self, content: str, instruction: str, text_selection: Dict[str, Any] = None, app_name: str = None) -> Dict[str, Any]:
        """
        Main entry point for context enhancement with personalization support.
        Detects operation type and delegates to appropriate specialized enhancer.
        
        Args:
            content: Raw OCR text or content (full document)
            instruction: User's voice instruction
            text_selection: Optional dict containing text selection data from frontend
            
        Returns:
            Dict containing:
            - context_type: Detected context type
            - filtered_content: Processed content
            - enhanced_prompt: Context-appropriate prompt
            - metadata: Additional context information
            - personalization_applied: Boolean indicating if personalization was used
        """
        try:
            # Load personalization first so selected-text suggestions retain
            # the same standing instructions as every other suggestion path.
            context_type = self._detect_context_by_application(app_name, content)
            personalization_context = await self._get_personalization_context(context_type, content, app_name)

            # Handle text selection scenarios first
            if text_selection and text_selection.get("has_selection", False):
                selected_text = text_selection.get("selected_text", "").strip()
                if selected_text:  # Only use selection enhancement if there's actual text
                    logger.info(f"Processing text selection context: '{selected_text[:30]}...'")
                    return self._append_instruction_priority(
                        self._build_selection_enhancement(content, instruction, text_selection),
                        personalization_context,
                    )
                else:
                    logger.info("has_selection was True but selected_text is empty - treating as no selection")
            
            if context_type == "email":
                logger.info(f"Detected email context (app: {app_name}), using email enhancer")
                result = await self.email_enhancer.enhance(content, instruction, personalization_context)
                logger.info(f"Email enhancement completed: type={result['context_type']}, content_length={len(result['filtered_content'])}")
                return self._append_instruction_priority(result, personalization_context)
            elif context_type == "social_media":
                logger.info(f"Detected social media context (app: {app_name}), using social media enhancer")
                result = self.social_media_enhancer.enhance(content, instruction, personalization_context)
                logger.info(f"Social media enhancement completed: type={result['context_type']}, content_length={len(result['filtered_content'])}")
                return self._append_instruction_priority(result, personalization_context)
            elif context_type == "document":
                logger.info(f"Detected document context (app: {app_name}), using document enhancer")
                result = self.document_enhancer.enhance(content, instruction, personalization_context)
                logger.info(f"Document enhancement completed: type={result['context_type']}, content_length={len(result['filtered_content'])}")
                return self._append_instruction_priority(result, personalization_context)
            elif context_type == "code":
                logger.info(f"Detected code context (app: {app_name}), using code enhancer")
                result = self.code_enhancer.enhance(content, instruction, personalization_context)
                logger.info(f"Code enhancement completed: type={result['context_type']}, content_length={len(result['filtered_content'])}")
                return self._append_instruction_priority(result, personalization_context)
            elif context_type == "browser":
                logger.info(f"Detected browser app ({app_name}), falling back to OCR pattern detection")
                # For browsers, fall back to OCR-based detection
                return self._append_instruction_priority(
                    await self._detect_context_by_ocr_patterns(content, instruction, personalization_context),
                    personalization_context,
                )
            
            # No specialized context detected, use generic enhancement
            logger.info("No specialized context detected, using generic enhancement")
            return self._append_instruction_priority(
                self._build_generic_enhancement(content, instruction, personalization_context),
                personalization_context,
            )
            
        except Exception as e:
            logger.error(f"Error in context enhancement: {e}")
            # Fallback to generic enhancement (no personalization_context: it may not
            # have been fetched yet if the exception happened before that point)
            return self._append_instruction_priority(
                self._build_generic_enhancement(content, instruction, error=str(e))
            )

    async def _get_personalization_context(
        self, 
        context_type: str, 
        content: str,
        app_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Centralized personalization context fetching for all enhancers.
        
        Args:
            context_type: Detected context type (email, document, social_media, code, etc.)
            content: Content to extract recipient from (for email contexts)
            app_name: Optional app name (Slack, Mail, Discord, Google Docs, etc.)
            
        Returns:
            Personalization context dict or None if unavailable
        """
        if not self.personalization_service:
            return None
        
        try:
            # Import ContextType enum
            from api.core.knowledge.personalization_models import ContextType
            
            participant_context = None
            recipient = None
            email_interaction_kind = EmailInteractionKind.GENERIC

            if context_type == "email":
                if self.email_enhancer._is_email_reply(content):
                    email_interaction_kind = EmailInteractionKind.REPLY
                elif self.email_enhancer._is_email_compose(content):
                    email_interaction_kind = EmailInteractionKind.COMPOSE
                participant_context = extract_email_participant_context(
                    content,
                    email_interaction_kind,
                )
                if participant_context.primary:
                    recipient = participant_context.primary.email

            # Map context types to enum values
            context_type_map = {
                "email": (
                    ContextType.EMAIL_COMPOSE
                    if email_interaction_kind == EmailInteractionKind.COMPOSE
                    else ContextType.EMAIL_REPLY
                ),
                "social_media": ContextType.SOCIAL_MEDIA,
                "document": ContextType.DOCUMENT,
                "code": ContextType.DOCUMENT,  # Code uses document style
            }
            
            enum_context_type = context_type_map.get(context_type, ContextType.DOCUMENT)
            
            context = await self.personalization_service.build_personalization_context(
                context_type=enum_context_type,
                recipient=recipient,
                app_name=app_name
            )
            
            # Only return if we actually have useful data
            if context and (
                context.profile
                or context.style
                or context.writing_samples
                or context.contact
                or context.signature
                or (participant_context and participant_context.primary)
            ):
                logger.info(f"📋 Personalization context retrieved for {context_type}")
                
                # Log detailed breakdown
                if context.profile:
                    logger.info(f"  👤 Profile: {context.profile.full_name or 'N/A'} ({context.profile.job_title or 'N/A'})")
                    logger.info(f"     Email: {context.profile.email or 'N/A'}")
                    logger.info(f"     Company: {context.profile.company_name or 'N/A'}")
                
                if context.style:
                    logger.info(
                        "  ✍️  Style: confidence=%s, samples=%s",
                        getattr(context.style, "confidence", "N/A"),
                        getattr(context.style, "sample_count", "N/A"),
                    )
                
                if context.writing_samples:
                    logger.info(f"  📝 Writing samples: {len(context.writing_samples)} included")
                    for i, sample in enumerate(context.writing_samples[:3], 1):  # Show first 3
                        preview = sample.content[:100].replace('\n', ' ') if sample.content else 'N/A'
                        app_info = f" | app={sample.app_name}" if sample.app_name else ""
                        recipient_info = f" | to={sample.recipient}" if sample.recipient else ""
                        logger.info(f"     Sample {i}: {sample.source_type} | {sample.context_type}{app_info}{recipient_info} | \"{preview}...\"")
                    if len(context.writing_samples) > 3:
                        logger.info(f"     ... and {len(context.writing_samples) - 3} more")
                
                if context.contact:
                    logger.info(f"  👥 Contact: {context.contact.contact_name or context.contact.contact_email}")
                    logger.info(f"     Relationship: {context.contact.relationship_type}, formality: {context.contact.formality_level}")
                    logger.info(f"     Interactions: {context.contact.message_count}, last: {context.contact.last_contact_date}")
                
                if context.signature:
                    sig_preview = context.signature.signature_text[:50].replace('\n', ' ') if context.signature.signature_text else 'N/A'
                    logger.info(
                        f"  ✒️  Signature: \"{sig_preview}...\" "
                        f"(used {getattr(context.signature, 'occurrence_count', 'N/A')} times)"
                    )
                
                # Convert to dict for easier template usage
                return {
                    "profile": context.profile,
                    "style": context.style,
                    "writing_samples": context.writing_samples,
                    "contact": context.contact,
                    "signature": context.signature,
                    "participant_context": participant_context,
                }
            
            logger.info(f"📋 No personalization context available for {context_type}")
            return None
            
        except Exception as e:
            logger.warning(f"Could not fetch personalization context: {e}")
            return None

    def build_personalization_section(self, personalization: Dict[str, Any]) -> str:
        """
        Build personalization section for prompt injection (shared across all enhancers).
        
        Args:
            personalization: Context dict from PersonalizationService
            
        Returns:
            Formatted personalization section for prompt
        """
        section = "\n"
        
        # Add user profile information
        profile = personalization.get("profile")
        if profile:
            section += "\nUSER IDENTITY AND ROLE:\n"
            if profile.full_name:
                section += f"- Name: {profile.full_name}\n"
            if profile.job_title and profile.company_name:
                section += f"- Role: {profile.job_title} at {profile.company_name}\n"
            elif profile.job_title:
                section += f"- Role: {profile.job_title}\n"
            if profile.industry:
                section += f"- Industry: {profile.industry}\n"

        participant_context = personalization.get("participant_context")
        if participant_context and getattr(participant_context, "primary", None):
            primary = participant_context.primary
            section += "\nEMAIL PARTICIPANT CONTEXT:\n"
            section += f"- Primary participant: {primary.label}\n"
            section += f"- Interaction type: {participant_context.interaction_kind.value}\n"
            if participant_context.cc_participants:
                cc_labels = ", ".join(participant.label for participant in participant_context.cc_participants[:3])
                section += f"- CC participants: {cc_labels}\n"
        
        # Add communication style if available - PRIORITIZE THE LLM-GENERATED SUMMARY
        style = personalization.get("style")
        if style and style.style_attributes:
            try:
                style_attrs = json.loads(style.style_attributes) if isinstance(style.style_attributes, str) else style.style_attributes
                if hasattr(style_attrs, "model_dump"):
                    style_attrs = style_attrs.model_dump()
                
                # Include LLM-generated style summary FIRST (most important)
                if style_attrs.get("style_summary"):
                    section += "\nLEARNED WRITING STYLE (AI Analysis):\n"
                    section += f"{style_attrs['style_summary']}\n"
                
                # Then add specific style attributes for additional detail
                section += "\nSTYLE DETAILS:\n"
                
                if style_attrs.get("formality_level") is not None:
                    formality_pct = int(style_attrs['formality_level'] * 100)
                    formality_desc = "very formal" if formality_pct > 70 else "professional" if formality_pct > 40 else "casual"
                    section += f"- Formality: {formality_desc} ({formality_pct}%)\n"
                
                if style_attrs.get("greeting_patterns"):
                    greetings = style_attrs['greeting_patterns'][:3]  # Limit to top 3
                    section += f"- Typical Greetings: {', '.join(greetings)}\n"
                
                if style_attrs.get("closing_patterns"):
                    closings = style_attrs['closing_patterns'][:3]  # Limit to top 3
                    section += f"- Typical Closings: {', '.join(closings)}\n"
                
                if style_attrs.get("common_phrases"):
                    phrases = style_attrs['common_phrases'][:5]  # Limit to top 5
                    section += f"- Common Phrases: {', '.join(phrases)}\n"
                
                if style_attrs.get("paragraph_structure"):
                    section += f"- Sentence Structure: {style_attrs['paragraph_structure']}\n"
                
                if "uses_contractions" in style_attrs:
                    uses = "Yes" if style_attrs["uses_contractions"] else "No"
                    section += f"- Uses Contractions: {uses}\n"
                
                if style_attrs.get("tone_markers"):
                    markers = style_attrs['tone_markers'][:5]  # Limit to top 5
                    section += f"- Tone Markers: {', '.join(markers)}\n"
                    
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Could not parse style attributes: {e}")
        
        # Add contact relationship information
        contact = personalization.get("contact")
        if contact:
            section += "\nRECIPIENT RELATIONSHIP:\n"
            if contact.contact_name:
                section += f"- Name: {contact.contact_name}\n"
            if contact.contact_company:
                section += f"- Organization: {contact.contact_company}\n"
            if contact.relationship_type and str(contact.relationship_type) != "unknown":
                section += f"- Relationship: {contact.relationship_type}\n"
            if contact.formality_level:
                section += f"- Typical Formality: {contact.formality_level}\n"
            if contact.message_count and contact.message_count > 0:
                section += f"- Communication History: {contact.message_count} previous exchanges\n"
        
        # Add writing samples (increased length for better voice capture)
        writing_samples = personalization.get("writing_samples", [])
        if writing_samples:
            section += "\nREFERENCE WRITING SAMPLES (from user's actual writing):\n"
            for i, sample in enumerate(writing_samples[:3], 1):  # Include all 3 samples
                recipient_info = f" (to {sample.recipient})" if sample.recipient else ""
                # Increased to 1000 chars to capture voice/style better
                truncated_content = sample.content[:1000] + "..." if len(sample.content) > 1000 else sample.content
                section += f"\nSample {i}{recipient_info}:\n{truncated_content}\n"
        
        return section

    def _extract_email_recipient(self, content: str) -> Optional[str]:
        """Extract email recipient from content for relationship-aware personalization."""
        # Try to find To: field
        to_match = re.search(r'To:\s*([^\n]+)', content, re.IGNORECASE)
        if to_match:
            recipient = to_match.group(1).strip()
            # Extract just the email if in "Name <email>" format
            email_match = re.search(r'<([^>]+)>', recipient)
            if email_match:
                return email_match.group(1)
            # Or if it's just an email address
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', recipient)
            if email_match:
                return email_match.group(0)
        return None

    def _is_email_context(self, content: str) -> bool:
        """Check if content appears to be from an email interface."""
        return any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                  for pattern in self.email_indicators)

    def _is_social_media_context(self, content: str) -> bool:
        """Check if content appears to be from a social media interface."""
        return any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                  for pattern in self.social_media_indicators)

    def _is_document_context(self, content: str) -> bool:
        """Check if content appears to be from a document editor interface."""
        return any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                  for pattern in self.document_indicators)

    def _is_code_context(self, content: str) -> bool:
        """Check if content appears to be from a code editor interface."""
        return any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                  for pattern in self.code_indicators)

    def _detect_context_by_application(self, app_name: str, content: str) -> str:
        """
        Primary context detection using application name.
        Falls back to OCR pattern matching if app name is unknown.
        
        Args:
            app_name: Name of the application (e.g., "Microsoft Word", "Gmail")
            content: OCR content for fallback detection
            
        Returns:
            Context type: "email", "document", "code", "social_media", "browser", or "unknown"
        """
        if not app_name or app_name.lower() in ("unknown", ""):
            logger.info("No app name provided, falling back to OCR pattern detection")
            return self._detect_context_by_ocr_fallback(content)
        
        # Check against application mappings
        if app_name in self.email_applications:
            return "email"
        elif app_name in self.document_applications:
            return "document"
        elif app_name in self.code_applications:
            return "code"
        elif app_name in self.social_media_applications:
            return "social_media"
        elif app_name in self.browser_applications:
            return "browser"
        else:
            logger.info(f"Unknown application '{app_name}', falling back to OCR pattern detection")
            return self._detect_context_by_ocr_fallback(content)

    async def _detect_context_by_ocr_patterns(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Fallback detection using OCR patterns when app name detection fails.
        Used primarily for browsers and unknown applications.
        """
        if self._is_email_context(content):
            logger.info("OCR fallback: Detected email context")
            result = await self.email_enhancer.enhance(content, instruction, personalization_context)
            return result
        elif self._is_social_media_context(content):
            logger.info("OCR fallback: Detected social media context")
            result = self.social_media_enhancer.enhance(content, instruction, personalization_context)
            return result
        elif self._is_document_context(content):
            logger.info("OCR fallback: Detected document context")
            result = self.document_enhancer.enhance(content, instruction, personalization_context)
            return result
        elif self._is_code_context(content):
            logger.info("OCR fallback: Detected code context")
            result = self.code_enhancer.enhance(content, instruction, personalization_context)
            return result
        else:
            logger.info("OCR fallback: No specialized context detected, using generic enhancement")
            return self._build_generic_enhancement(content, instruction, personalization_context)

    def _detect_context_by_ocr_fallback(self, content: str) -> str:
        """
        Simple OCR-based context detection that returns just the context type.
        Used when app name is unavailable or unknown.
        """
        if self._is_email_context(content):
            return "email"
        elif self._is_social_media_context(content):
            return "social_media"
        elif self._is_document_context(content):
            return "document"
        elif self._is_code_context(content):
            return "code"
        else:
            return "unknown"



    def _build_generic_enhancement(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None, error: str = None) -> Dict[str, Any]:
        """Build generic enhancement when no specialized enhancer is available."""
        metadata = {"enhancer": "generic"}
        if error:
            metadata["error"] = error
        if personalization_context:
            metadata["personalization_applied"] = True
        
        enhanced_prompt = f"""You are an AI assistant helping the user with their request.

INSTRUCTIONS:
- Follow the user's instruction precisely
- Use the provided content as context
- Be concise and professional
- Do not add unnecessary commentary or formatting

IMPORTANT: Only include the original screen content in your response if the user explicitly requests it to be processed, edited, reformatted, or transformed (e.g., "fix this text", "rewrite this", "format this document", "take what's here and...", etc.). Otherwise, provide a clean response without repeating the screen content.

CURRENT SCREEN CONTENT:
{content}

USER INSTRUCTION: {instruction}

Response:"""

        return {
            "context_type": "generic",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _build_selection_enhancement(self, full_content: str, instruction: str, text_selection: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build enhancement for text selection scenarios.
        Provides both selected text and full context to the model, letting it intelligently decide
        how to prioritize based on the user's instruction.
        """
        selected_text = text_selection.get("selected_text", "")
        containing_text = text_selection.get("containing_text", full_content)
        app_name = text_selection.get("application_name", "Unknown")
        confidence = text_selection.get("confidence", 0.0)
        
        logger.info(f"Building selection-aware prompt for: '{instruction}'")
        
        # Single flexible prompt that lets the model decide how to use the selection
        enhanced_prompt = f"""You are an AI assistant helping with a user request. The user has highlighted specific text on their screen.

USER'S REQUEST: {instruction}

HIGHLIGHTED TEXT (what the user selected):
{selected_text}

FULL SCREEN CONTEXT (for reference):
{full_content}

INSTRUCTIONS:
- The user has explicitly highlighted the text shown above
- If their request seems to pertain to the highlighted text (e.g., "expand this", "improve this", "rewrite this"), focus your response on that specific text
- If their request is more general or document-wide, use all available context
- When working with highlighted text, provide output that directly addresses or enhances what was selected
- Be intelligent about understanding user intent - you don't need explicit keywords to know if they're referring to the selection
- Return a complete, useful response that the user can directly use

Response:"""
        
        metadata = {
            "enhancer": "text_selection",
            "selected_text_length": len(selected_text),
            "full_content_length": len(full_content),
            "app_name": app_name,
            "confidence": confidence
        }
        
        return {
            "context_type": "selection_aware",
            "filtered_content": full_content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    async def enhance_refinement_context(self, initial_context: str, initial_request: str, 
                                  previous_output: str, refinement_request: str, 
                                  app_name: str = None) -> str:
        """
        Build enhanced prompt for refinement requests by leveraging existing specialized enhancers.
        This ensures all domain-specific rules (like email signature handling) are preserved.
        """
        # Create a refinement-aware instruction that includes the refinement context
        refinement_instruction = f"""REFINEMENT MODE: The user wants to refine a previous response.

PREVIOUS OUTPUT TO REFINE:
{previous_output}

WHAT TO CHANGE: {refinement_request}

ORIGINAL REQUEST (for context only): {initial_request}

Produce the complete updated version incorporating the requested change. Preserve everything the user did not ask you to change. Do not comment on the refinement process, do not narrate what you changed or why, and do not say things like "I see you want me to..." — just output the result."""

        # Use the existing specialized enhancers with the refinement-aware instruction
        # This ensures all domain-specific rules (signatures, formatting, etc.) are preserved
        context_type = self._detect_context_by_application(app_name, initial_context)
        
        # Fetch personalization context once (centralized)
        personalization_context = await self._get_personalization_context(context_type, initial_context, app_name)
        
        if context_type == "email":
            result = await self.email_enhancer.enhance(initial_context, refinement_instruction, personalization_context)
            return result["enhanced_prompt"]
        elif context_type == "document":
            result = self.document_enhancer.enhance(initial_context, refinement_instruction, personalization_context)
            return result["enhanced_prompt"]
        elif context_type == "social_media":
            result = self.social_media_enhancer.enhance(initial_context, refinement_instruction, personalization_context)
            return result["enhanced_prompt"]
        elif context_type == "code":
            result = self.code_enhancer.enhance(initial_context, refinement_instruction, personalization_context)
            return result["enhanced_prompt"]
        else:
            # For generic context, use the existing generic enhancement
            result = self._build_generic_enhancement(initial_context, refinement_instruction, personalization_context)
            return result["enhanced_prompt"]   