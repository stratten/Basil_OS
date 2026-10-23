import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AssistantSessionDocumentEnhancer:
    """
    Specialized context enhancer for document/text editor AssistantSession suggestions.
    Handles academic writing, business documents, creative writing, technical documentation, and note-taking.
    """
    
    def __init__(self, coordinator=None):
        self.coordinator = coordinator  # Reference to AssistantSessionContextEnhancer for shared methods
        # Document/text editor detection patterns
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
        
        # Academic writing patterns
        self.academic_indicators = [
            r"Abstract:|Introduction:|Literature Review:|Methodology:|Results:|Discussion:|Conclusion:",
            r"References|Bibliography|Citations?",
            r"Figure \d+|Table \d+|Appendix [A-Z]",
            r"et al\.|ibid\.|op\. cit\.",
            r"Research|Study|Analysis|Hypothesis",
            r"DOI:|ISBN:|ISSN:",
            r"University|Department|Faculty",
            r"Thesis|Dissertation|Paper|Journal"
        ]
        
        # Business document patterns
        self.business_indicators = [
            r"Executive Summary|Business Plan|Proposal",
            r"Action Items?|Next Steps?|Deliverables?",
            r"Timeline|Milestone|Deadline",
            r"Budget|Cost|Revenue|ROI",
            r"Stakeholder|Client|Customer",
            r"Meeting Minutes|Agenda|Action Plan",
            r"Strategy|Objectives?|Goals?",
            r"Quarterly|Annual|Monthly Report"
        ]
        
        # Creative writing patterns
        self.creative_indicators = [
            r"Chapter \d+|Scene \d+|Act \d+",
            r"Character|Protagonist|Antagonist",
            r"Dialogue|Narrative|Plot",
            r"Draft \d+|Revision|Edit",
            r"Story|Novel|Fiction|Poetry",
            r"Setting|Theme|Conflict",
            r"Manuscript|Screenplay|Script"
        ]
        
        # Technical documentation patterns
        self.technical_indicators = [
            r"API|Documentation|Manual|Guide",
            r"Installation|Configuration|Setup",
            r"Code|Function|Method|Class",
            r"Parameter|Argument|Return",
            r"Example|Usage|Implementation",
            r"Version \d+\.\d+|Release Notes",
            r"Prerequisites|Requirements|Dependencies",
            r"Troubleshooting|FAQ|Support"
        ]
        
        # Note-taking patterns
        self.notes_indicators = [
            r"Notes?|Notebook|Journal",
            r"TODO|FIXME|NOTE|IMPORTANT",
            r"Meeting Notes|Class Notes|Research Notes",
            r"Bullet Journal|Daily Notes|Weekly Review",
            r"Tags?:|Categories?:|Labels?:",
            r"Brainstorm|Ideas?|Thoughts?",
            r"Summary|Key Points|Takeaways?"
        ]

    def enhance(self, content: str, instruction: str, personalization_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhance document/text editor-specific AssistantSession suggestions with personalization support.
        
        Args:
            content: Raw OCR text from document/text editor interface
            instruction: User's voice instruction
            personalization_context: Optional personalization data from orchestrator
            
        Returns:
            Enhancement result with document-specific processing
        """
        try:
            # Detect specific document type
            document_type = self._detect_document_type(content)
            
            if document_type == "academic":
                return self._enhance_academic_document(content, instruction, personalization_context)
            elif document_type == "business":
                return self._enhance_business_document(content, instruction, personalization_context)
            elif document_type == "creative":
                return self._enhance_creative_document(content, instruction, personalization_context)
            elif document_type == "technical":
                return self._enhance_technical_document(content, instruction, personalization_context)
            elif document_type == "notes":
                return self._enhance_notes_document(content, instruction, personalization_context)
            else:
                # Generic document context
                return self._enhance_generic_document(content, instruction, personalization_context)
                
        except Exception as e:
            logger.error(f"Error in document enhancement: {e}")
            return {
                "context_type": "document_generic",
                "filtered_content": content,
                "enhanced_prompt": self._build_fallback_prompt(content, instruction),
                "metadata": {"error": str(e), "enhancer": "document"}
            }

    def _detect_document_type(self, content: str) -> str:
        """Detect specific document type from content."""
        if any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
               for pattern in self.academic_indicators):
            return "academic"
        elif any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                 for pattern in self.business_indicators):
            return "business"
        elif any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                 for pattern in self.creative_indicators):
            return "creative"
        elif any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                 for pattern in self.technical_indicators):
            return "technical"
        elif any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) 
                 for pattern in self.notes_indicators):
            return "notes"
        else:
            return "generic_document"

    def _enhance_academic_document(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle academic writing enhancement."""
        metadata = self._extract_academic_metadata(content)
        metadata["enhancer"] = "document"
        metadata["document_type"] = "academic"
        
        enhanced_prompt = self._build_academic_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "document_academic",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_business_document(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle business document enhancement."""
        metadata = self._extract_business_metadata(content)
        metadata["enhancer"] = "document"
        metadata["document_type"] = "business"
        
        enhanced_prompt = self._build_business_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "document_business",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_creative_document(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle creative writing enhancement."""
        metadata = self._extract_creative_metadata(content)
        metadata["enhancer"] = "document"
        metadata["document_type"] = "creative"
        
        enhanced_prompt = self._build_creative_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "document_creative",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_technical_document(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle technical documentation enhancement."""
        metadata = self._extract_technical_metadata(content)
        metadata["enhancer"] = "document"
        metadata["document_type"] = "technical"
        
        enhanced_prompt = self._build_technical_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "document_technical",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_notes_document(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle note-taking enhancement."""
        metadata = self._extract_notes_metadata(content)
        metadata["enhancer"] = "document"
        metadata["document_type"] = "notes"
        
        enhanced_prompt = self._build_notes_prompt(content, instruction, metadata, personalization)
        
        return {
            "context_type": "document_notes",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _enhance_generic_document(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle generic document enhancement."""
        metadata = {"enhancer": "document", "document_type": "generic_document"}
        enhanced_prompt = self._build_generic_document_prompt(content, instruction, personalization)
        
        return {
            "context_type": "document_generic",
            "filtered_content": content,
            "enhanced_prompt": enhanced_prompt,
            "metadata": metadata
        }

    def _extract_academic_metadata(self, content: str) -> Dict[str, Any]:
        """Extract academic writing-specific metadata."""
        metadata = {}
        
        # Detect academic sections
        sections = []
        for pattern in ["Abstract:", "Introduction:", "Literature Review:", "Methodology:", "Results:", "Discussion:", "Conclusion:"]:
            if re.search(pattern, content, re.IGNORECASE):
                sections.append(pattern.rstrip(':').lower())
        
        if sections:
            metadata["sections_present"] = sections
        
        # Check for citations
        citation_patterns = re.findall(r"\([A-Za-z]+,?\s*\d{4}\)", content)
        if citation_patterns:
            metadata["has_citations"] = True
            metadata["citation_count"] = len(citation_patterns)
        
        # Check for figures/tables
        figures = re.findall(r"Figure \d+", content, re.IGNORECASE)
        tables = re.findall(r"Table \d+", content, re.IGNORECASE)
        
        if figures:
            metadata["figures"] = len(figures)
        if tables:
            metadata["tables"] = len(tables)
            
        return metadata

    def _extract_business_metadata(self, content: str) -> Dict[str, Any]:
        """Extract business document-specific metadata."""
        metadata = {}
        
        # Check for action items
        action_items = re.findall(r"Action Item[s]?:|TODO:|Next Step[s]?:", content, re.IGNORECASE)
        if action_items:
            metadata["has_action_items"] = True
        
        # Check for timeline/deadline references
        timeline_refs = re.findall(r"deadline|timeline|due date|milestone", content, re.IGNORECASE)
        if timeline_refs:
            metadata["has_timeline"] = True
        
        # Check for financial terms
        financial_terms = re.findall(r"\$[\d,]+|budget|cost|revenue|ROI|profit", content, re.IGNORECASE)
        if financial_terms:
            metadata["has_financial_content"] = True
            
        return metadata

    def _extract_creative_metadata(self, content: str) -> Dict[str, Any]:
        """Extract creative writing-specific metadata."""
        metadata = {}
        
        # Check for story structure elements
        if re.search(r"Chapter \d+", content, re.IGNORECASE):
            metadata["structure_type"] = "chapters"
        elif re.search(r"Scene \d+", content, re.IGNORECASE):
            metadata["structure_type"] = "scenes"
        elif re.search(r"Act \d+", content, re.IGNORECASE):
            metadata["structure_type"] = "acts"
        
        # Check for dialogue
        dialogue_indicators = re.findall(r'"[^"]*"', content)
        if len(dialogue_indicators) > 2:
            metadata["has_dialogue"] = True
        
        # Check for character names (capitalized words that might be names)
        potential_characters = re.findall(r'\b[A-Z][a-z]+\b(?:\s+[A-Z][a-z]+)*', content)
        if len(potential_characters) > 3:
            metadata["character_heavy"] = True
            
        return metadata

    def _extract_technical_metadata(self, content: str) -> Dict[str, Any]:
        """Extract technical documentation-specific metadata."""
        metadata = {}
        
        # Check for code elements
        code_indicators = re.findall(r"`[^`]+`|```[^```]+```", content)
        if code_indicators:
            metadata["has_code_examples"] = True
            metadata["code_example_count"] = len(code_indicators)
        
        # Check for API documentation
        api_patterns = re.findall(r"GET|POST|PUT|DELETE|API|endpoint", content, re.IGNORECASE)
        if api_patterns:
            metadata["api_documentation"] = True
        
        # Check for version information
        version_match = re.search(r"[Vv]ersion\s*(\d+\.\d+(?:\.\d+)?)", content)
        if version_match:
            metadata["version"] = version_match.group(1)
            
        return metadata

    def _extract_notes_metadata(self, content: str) -> Dict[str, Any]:
        """Extract note-taking-specific metadata."""
        metadata = {}
        
        # Check for TODO items
        todos = re.findall(r"TODO|FIXME|NOTE|IMPORTANT", content, re.IGNORECASE)
        if todos:
            metadata["has_todos"] = True
            metadata["todo_count"] = len(todos)
        
        # Check for bullet points
        bullets = re.findall(r"^\s*[-*+]\s+", content, re.MULTILINE)
        if bullets:
            metadata["bullet_points"] = len(bullets)
        
        # Check for tags/categories
        tags = re.findall(r"#\w+|@\w+|\[\[\w+\]\]", content)
        if tags:
            metadata["has_tags"] = True
            metadata["tag_count"] = len(tags)
            
        return metadata

    def _build_academic_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build academic writing-specific prompt."""
        section_info = ""
        if "sections_present" in metadata:
            section_info = f"\n- Document sections detected: {', '.join(metadata['sections_present'])}"
        
        citation_info = ""
        if metadata.get("has_citations", False):
            citation_info = f"\n- Citations present ({metadata.get('citation_count', 0)} found) - maintain academic citation style"
        
        structure_info = ""
        if metadata.get("figures", 0) > 0 or metadata.get("tables", 0) > 0:
            structure_info = f"\n- Contains figures/tables - maintain formal academic structure"
        
        base_prompt = f"""You are a skilled academic writing ghostwriter who excels at capturing someone's authentic scholarly voice and academic communication style. Your expertise is creating academic content that sounds exactly like the person wrote it while maintaining rigorous scholarly standards.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural academic voice, vocabulary, and scholarly communication patterns
- Capture their unique way of presenting academic arguments and structuring scholarly thoughts
- Sound like genuine scholarly writing, not generic academic templates or AI-generated content
- Maintain their authentic intellectual personality while adhering to academic conventions
- Be concise and clear while maintaining the person's authentic scholarly style and voice

ACADEMIC COMMUNICATION ADAPTATION:
- Analyze the document content and academic context to understand the intended scholarly audience
- If the context suggests expert researchers: maintain sophisticated theoretical depth and specialized terminology
- If the context suggests broader academic audience: balance rigor with accessibility using clear explanations
- If the context suggests student-oriented content: emphasize educational clarity while maintaining scholarly integrity
- If interdisciplinary context: bridge disciplines using their natural explanatory style and accessible language
- Adapt complexity appropriately while preserving their authentic academic voice and analytical approach

SCHOLARLY WRITING APPROACH:
- Use formal, scholarly tone that matches their natural academic voice and intellectual style{section_info}{citation_info}{structure_info}
- Maintain academic structure and organization in their preferred scholarly format
- Be precise and evidence-based using their natural argumentation style
- Support statements with reasoning in their authentic analytical voice
- Ensure logical flow that reflects their natural intellectual progression
- Connect complex academic concepts using their preferred explanatory methods

CRITICAL: OUTPUT ONLY THE ACADEMIC CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about academic style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain academic way unless explicitly requested by the user
- Do NOT include phrases like "Based on the academic context" or "Looking at the scholarly content" unless explicitly requested by the user
- Do NOT provide commentary about the person's academic voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual academic content
- The first word of your response should be the beginning of the academic content itself
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
CURRENT ACADEMIC DOCUMENT:
{content}

USER INSTRUCTION: {instruction}

ACADEMIC CONTENT:"""
        
        return base_prompt

    def _build_business_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build business document-specific prompt."""
        action_info = ""
        if metadata.get("has_action_items", False):
            action_info = "\n- Action items detected - maintain clear, actionable language"
        
        timeline_info = ""
        if metadata.get("has_timeline", False):
            timeline_info = "\n- Timeline/deadline context - be specific about timing and deliverables"
        
        financial_info = ""
        if metadata.get("has_financial_content", False):
            financial_info = "\n- Financial content detected - be precise with numbers and business terminology"
        
        base_prompt = f"""You are a skilled business writing ghostwriter who excels at capturing someone's authentic professional voice and communication style. Your expertise is creating business documents that sound exactly like the person wrote them.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural professional voice, vocabulary, and communication patterns
- Capture their unique way of structuring business thoughts and presenting ideas
- Sound like genuine professional communication, not corporate template language
- Maintain their authentic leadership style and business personality
- Be concise and clear while maintaining the person's authentic professional style and voice

CONTEXTUAL AUDIENCE ADAPTATION:
- Analyze the document content and context to understand the intended audience
- If the context suggests technical stakeholders: maintain appropriate technical depth while ensuring business relevance
- If the context suggests executive/leadership audience: focus on strategic outcomes and high-level implications
- If the context suggests operational teams: emphasize practical implementation and actionable steps
- If mixed audience: balance technical accuracy with broader business accessibility
- Adapt complexity and terminology to match the apparent business context and audience needs

BUSINESS COMMUNICATION APPROACH:
- Focus on actionable outcomes and measurable results relevant to the detected audience{action_info}{timeline_info}{financial_info}
- Use their natural level of formality and business terminology
- Structure information appropriately for the audience while maintaining their authentic voice
- Include specific details and concrete examples in their natural communication style
- Connect complex topics to business outcomes meaningful to the intended audience

CRITICAL: OUTPUT ONLY THE BUSINESS CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about business style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain business way unless explicitly requested by the user
- Do NOT include phrases like "Based on the business context" or "Looking at the professional content" unless explicitly requested by the user
- Do NOT provide commentary about the person's professional voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual business content
- The first word of your response should be the beginning of the business content itself
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
CURRENT BUSINESS DOCUMENT:
{content}

USER INSTRUCTION: {instruction}

BUSINESS CONTENT:"""
        
        return base_prompt

    def _build_creative_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build creative writing-specific prompt."""
        structure_info = ""
        if "structure_type" in metadata:
            structure_info = f"\n- Story structure: {metadata['structure_type']} - maintain narrative consistency"
        
        dialogue_info = ""
        if metadata.get("has_dialogue", False):
            dialogue_info = "\n- Dialogue present - maintain character voice and natural conversation flow"
        
        character_info = ""
        if metadata.get("character_heavy", False):
            character_info = "\n- Character-heavy content - maintain character consistency and development"
        
        base_prompt = f"""You are a masterful creative writing ghostwriter who specializes in perfectly capturing and preserving an author's unique voice, style, and artistic vision. Your expertise is creating content that seamlessly blends with their existing work.

CORE GHOSTWRITING PRINCIPLES:
- Preserve the author's completely unique voice, style, and artistic personality
- Mirror their specific vocabulary, sentence structure, and storytelling patterns
- Capture their natural rhythm, pacing, and narrative flow
- Maintain their authentic creative voice so no reader could tell the difference
- Be concise and clear while maintaining the person's authentic creative style and voice

ARTISTIC VOICE PRESERVATION:
- Study and mirror their specific word choices, metaphors, and descriptive language
- Maintain their natural dialogue style and character voice patterns
- Preserve their unique narrative perspective and storytelling approach
- Keep their established tone, mood, and atmospheric style consistent

CREATIVE STORYTELLING APPROACH:
- Focus on engaging storytelling that enhances the narrative while staying true to their voice{structure_info}{dialogue_info}{character_info}
- Use vivid, descriptive language that matches their established writing style
- Ensure dialogue feels natural and authentic to both characters and the author's style
- Maintain narrative consistency with their established world and character development

CRITICAL: OUTPUT ONLY THE CREATIVE CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about creative style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain creative way unless explicitly requested by the user
- Do NOT include phrases like "Based on the narrative context" or "Looking at the creative content" unless explicitly requested by the user
- Do NOT provide commentary about the person's creative voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual creative content
- The first word of your response should be the beginning of the creative content itself
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
CURRENT CREATIVE WORK:
{content}

USER INSTRUCTION: {instruction}

CREATIVE CONTENT:"""
        
        return base_prompt

    def _build_technical_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build technical documentation-specific prompt."""
        code_info = ""
        if metadata.get("has_code_examples", False):
            code_info = f"\n- Code examples present ({metadata.get('code_example_count', 0)}) - maintain technical accuracy"
        
        api_info = ""
        if metadata.get("api_documentation", False):
            api_info = "\n- API documentation context - be precise with technical specifications"
        
        version_info = ""
        if "version" in metadata:
            version_info = f"\n- Version {metadata['version']} context - ensure version-specific accuracy"
        
        base_prompt = f"""You are a skilled technical writing ghostwriter who excels at capturing someone's authentic technical communication style and expertise presentation. Your specialty is creating technical documentation that sounds exactly like the person wrote it while maintaining rigorous technical accuracy.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural technical voice, vocabulary, and communication patterns
- Capture their unique way of explaining technical concepts and structuring documentation
- Sound like genuine technical expertise, not generic documentation templates or AI-generated content
- Maintain their authentic teaching style and technical personality
- Be concise and clear while maintaining the person's authentic technical style and voice

TECHNICAL AUDIENCE ADAPTATION:
- Analyze the documentation content and context to understand the intended technical audience
- If the context suggests expert developers: maintain sophisticated technical depth and specialized terminology
- If the context suggests broader developer audience: balance technical accuracy with clear explanations
- If the context suggests mixed technical levels: provide layered information using their natural explanatory approach
- If the context suggests user-focused documentation: emphasize practical implementation in accessible language
- Adapt complexity appropriately while preserving their authentic technical voice and expertise

TECHNICAL DOCUMENTATION APPROACH:
- Use clear, precise, and unambiguous language in their natural technical communication style{code_info}{api_info}{version_info}
- Maintain technical accuracy and consistency using their preferred terminology and explanations
- Structure information for the appropriate technical audience while maintaining their authentic voice
- Include specific implementation details in their natural instructional style
- Use proper technical terminology in their preferred explanatory manner
- Ensure step-by-step clarity that reflects their natural teaching approach

CRITICAL: OUTPUT ONLY THE TECHNICAL CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about technical style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain technical way unless explicitly requested by the user
- Do NOT include phrases like "Based on the technical context" or "Looking at the documentation" unless explicitly requested by the user
- Do NOT provide commentary about the person's technical voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual technical content
- The first word of your response should be the beginning of the technical content itself
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
CURRENT TECHNICAL DOCUMENTATION:
{content}

USER INSTRUCTION: {instruction}

TECHNICAL CONTENT:"""
        
        return base_prompt

    def _build_notes_prompt(self, content: str, instruction: str, metadata: Dict[str, Any], personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build note-taking-specific prompt."""
        todo_info = ""
        if metadata.get("has_todos", False):
            todo_info = f"\n- TODO items present ({metadata.get('todo_count', 0)}) - maintain task organization"
        
        bullet_info = ""
        if metadata.get("bullet_points", 0) > 0:
            bullet_info = f"\n- Bullet point structure ({metadata['bullet_points']} points) - maintain organized format"
        
        tag_info = ""
        if metadata.get("has_tags", False):
            tag_info = f"\n- Tags/categories present ({metadata.get('tag_count', 0)}) - maintain organizational system"
        
        base_prompt = f"""You are a skilled personal note-taking ghostwriter who excels at capturing someone's authentic thinking style and personal knowledge management approach. Your expertise is creating notes that perfectly match their natural note-taking voice.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural thinking patterns and note-taking style
- Capture their unique way of organizing thoughts, ideas, and information
- Sound like genuine personal notes, not formal or AI-generated content
- Maintain their authentic voice and personality in personal knowledge capture
- Be concise and clear while maintaining the person's authentic note-taking style and voice

PERSONAL STYLE ADAPTATION:
- If they use technical terms: explain complex concepts in their natural way of breaking things down
- If they're non-technical: use clear, everyday language and relatable examples
- Match their natural level of detail and organizational preferences
- Preserve their authentic way of connecting ideas and making insights

NOTE-TAKING APPROACH:
- Keep information concise and well-organized in their natural style{todo_info}{bullet_info}{tag_info}
- Maintain their existing organizational system and formatting preferences
- Focus on key insights and actionable information in their natural voice
- Use consistent formatting that matches their personal note-taking patterns
- Make content easily scannable and retrievable in their preferred style

CRITICAL: OUTPUT ONLY THE NOTE CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about note-taking style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're organizing in a certain way unless explicitly requested by the user
- Do NOT include phrases like "Based on the note context" or "Looking at the organization style" unless explicitly requested by the user
- Do NOT provide commentary about the person's note-taking voice or style unless explicitly requested by the user
- START IMMEDIATELY with the actual note content
- The first word of your response should be the beginning of the note content itself
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
CURRENT NOTES:
{content}

USER INSTRUCTION: {instruction}

NOTE CONTENT:"""
        
        return base_prompt

    def _build_generic_document_prompt(self, content: str, instruction: str, personalization: Optional[Dict[str, Any]] = None) -> str:
        """Build prompt for generic document contexts."""
        base_prompt = f"""You are a versatile writing ghostwriter who excels at capturing someone's authentic voice and communication style across different types of documents. Your expertise is creating content that sounds exactly like the person wrote it.

CORE GHOSTWRITING PRINCIPLES:
- Write with complete authenticity - mirror their natural voice, vocabulary, and communication patterns
- Capture their unique way of structuring thoughts and expressing ideas in writing
- Sound like genuine personal writing, not generic or template-based content
- Adapt to the appropriate level of formality while maintaining their authentic voice
- Be concise and clear while maintaining the person's authentic style and voice

COMMUNICATION EFFECTIVENESS:
- If discussing technical topics: explain them in their natural way using clear language and assistant_session examples
- If the audience may be non-technical: break down complex concepts into understandable, relatable terms
- Use their natural teaching style and analogies that make expertise accessible
- Maintain their authentic voice while ensuring clarity and effectiveness

DOCUMENT WRITING APPROACH:
- Use clear, well-structured language that matches their natural writing style
- Maintain consistent tone and style that reflects their personality throughout
- Focus on readability and logical organization in their preferred structure
- Ensure proper grammar and formatting while preserving their authentic voice
- Adapt tone to match the document's purpose while staying true to their natural style

CRITICAL: OUTPUT ONLY THE DOCUMENT CONTENT - unless specifically requested otherwise by the user
- Do NOT include any meta-commentary about writing style, approach, or analysis unless explicitly requested by the user
- Do NOT explain what you're doing or why you're writing in a certain way unless explicitly requested by the user
- Do NOT include phrases like "Based on the document context" or "Looking at the writing style" unless explicitly requested by the user
- Do NOT provide commentary about the person's voice or writing style unless explicitly requested by the user
- START IMMEDIATELY with the actual document content
- The first word of your response should be the beginning of the document content itself
"""

        # Add personalization section if available
        if personalization and self.coordinator:
            base_prompt += self.coordinator.build_personalization_section(personalization)
        
        base_prompt += f"""
CURRENT DOCUMENT:
{content}

USER INSTRUCTION: {instruction}

DOCUMENT CONTENT:"""
        
        return base_prompt

    def _build_fallback_prompt(self, content: str, instruction: str) -> str:
        """Build fallback prompt when enhancement fails."""
        return f"""You are an AI assistant helping with a document writing task.

CONTENT:
{content}

USER INSTRUCTION: {instruction}

Response:"""