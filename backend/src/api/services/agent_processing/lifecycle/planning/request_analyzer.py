"""
Intelligent Request Analyzer

Analyzes user requests to:
1. Provide basic structural metrics
2. Interpret intent using chain context when available
3. Correct likely transcription errors
4. Resolve ambiguous references
5. Establish clear success criteria
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RequestAnalysis:
    """Request analysis with metrics, interpretation, and success criteria."""
    # Basic metrics
    text_length: int
    word_count: int  
    sentence_count: int
    character_variety: float  # Ratio of unique chars to total chars
    reasoning: List[str]
    
    # Intelligent interpretation
    interpreted_agent_task: Optional[str] = None  # Clarified/corrected agent task
    interpretation_applied: bool = False  # Whether intelligent interpretation was used
    interpretation_notes: List[str] = field(default_factory=list)  # What was clarified
    success_criteria: List[str] = field(default_factory=list)  # Expected outcomes


class RequestAnalyzer:
    """
    Intelligent request analyzer that provides:
    1. Basic text metrics for structural analysis
    2. Intent interpretation using chain context
    3. Transcription error correction
    4. Ambiguous reference resolution
    5. Success criteria establishment
    """
    
    def __init__(self, llm_model=None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.llm_model = llm_model
        
    async def analyze_request(self, user_agent_task: str, context: Dict[str, Any]) -> RequestAnalysis:
        """
        Analyze request with basic metrics and intelligent interpretation.
        
        Args:
            user_agent_task: The user's agent task to analyze
            context: Additional context information (may include chain_context)
            
        Returns:
            RequestAnalysis with metrics, interpretation, and success criteria
        """
        self.logger.info(f"🔍 ANALYZING REQUEST: {user_agent_task}")
        
        # Basic text properties
        text_length = len(user_agent_task)
        word_count = len(user_agent_task.split())
        sentence_count = user_agent_task.count('.') + user_agent_task.count('!') + user_agent_task.count('?') + 1
        
        # Character variety (measure of text complexity)
        unique_chars = len(set(user_agent_task.lower()))
        total_chars = len(user_agent_task.replace(' ', ''))  # Exclude spaces
        character_variety = unique_chars / max(total_chars, 1)
        
        reasoning = [
            f"Text length: {text_length} characters",
            f"Word count: {word_count}",
            f"Estimated sentences: {sentence_count}",
            f"Character variety: {character_variety:.2f}"
        ]
        
        # Intelligent interpretation is intentionally disabled (2026-07-23).
        #
        # This pre-step made a BLOCKING LLM call (max_tokens=500, web search on)
        # on every follow-up to rewrite the prompt / resolve references, but its
        # output was never consumed downstream: execution, synthesis, and finalize
        # all use the raw user_agent_task. A retrospective over 67 real follow-up
        # turns (backend/scripts/analyzer_retrospective.py) showed the call returned
        # truncated, unparseable JSON and silently no-op'd ~76% of the time, and
        # the ~22% that did resolve references were already handled by the agent's
        # own chain-context reasoning; the failures it might have fixed were
        # data-availability problems (see P4/recall), not prompt wording. Net: it
        # was pure head-of-turn latency for no benefit, so the blocking call is
        # removed from the critical path. The cheap text metrics above are kept
        # and the RequestAnalysis contract is unchanged (interpretation fields
        # simply stay at their no-op defaults). _interpret_with_context is kept
        # intact below so this can be re-enabled deliberately (with a larger
        # max_tokens) if a future design actually consumes the interpretation.
        interpreted_agent_task = None
        interpretation_applied = False
        interpretation_notes = []
        success_criteria = []
        
        analysis = RequestAnalysis(
            text_length=text_length,
            word_count=word_count,
            sentence_count=sentence_count,
            character_variety=character_variety,
            reasoning=reasoning,
            interpreted_agent_task=interpreted_agent_task,
            interpretation_applied=interpretation_applied,
            interpretation_notes=interpretation_notes,
            success_criteria=success_criteria
        )
        
        self.logger.info(f"📊 ANALYSIS COMPLETE: {text_length} chars, {word_count} words, interpretation=disabled")
        
        return analysis 
    
    async def _interpret_with_context(self, user_agent_task: str, chain_context: Dict[str, Any], reference_paths: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Use LLM to intelligently interpret the agent task based on chain context.
        
        Handles:
        - Transcription error correction (e.g., "workdown" → "markdown")
        - Ambiguous reference resolution (e.g., "this", "that", "the previous output")
        - Intent clarification based on conversation history
        - Success criteria establishment
        - Reference paths resolution (e.g., "these files", "this folder")
        
        Args:
            user_agent_task: The raw transcribed agent task
            chain_context: Context from previous agent tasks in the chain
            reference_paths: Optional list of file/folder paths dropped onto the widget
            
        Returns:
            Dict with interpreted_agent_task, interpretation_notes, and success_criteria
        """
        try:
            # Build context from chain history
            chain_agentTasks = chain_context.get('chain_agentTasks') or []
            if not chain_agentTasks and not reference_paths:
                return None
            
            context_summary = ""
            
            # Add reference paths section if provided
            if reference_paths:
                context_summary += "REFERENCE MATERIALS (files/folders provided by user):\n"
                for path in reference_paths:
                    context_summary += f"  - {path}\n"
                context_summary += "When the user says 'these files', 'this folder', 'these documents', etc., they mean the above paths.\n\n"
            
            # Add chain history
            if chain_agentTasks:
                context_summary += "PREVIOUS AGENT TASKS IN THIS CONVERSATION:\n"
                for agent_task_record in chain_agentTasks:
                    context_summary += f"\n{agent_task_record.get('sequence', '?')}. \"{agent_task_record.get('text', 'N/A')}\"\n"
                    if agent_task_record.get('result'):
                        result_preview = str(agent_task_record['result'])[:200]  # First 200 chars
                        context_summary += f"   Result: {result_preview}...\n"
            
            interpretation_prompt = f"""You are analyzing a user's agent_task in the context of a conversation chain.

{context_summary}

CURRENT AGENT TASK (just transcribed):
"{user_agent_task}"

YOUR TASK:
1. Check for likely transcription errors based on context (e.g., "workdown" should be "markdown" if previous output was markdown)
2. Resolve ambiguous references like "this", "that", "the previous output", "it" based on chain history
3. Clarify the user's actual intent
4. Establish clear success criteria for what would make this agent task successful

RESPONSE FORMAT (JSON only):
{{
    "interpreted_agent_task": "the clarified/corrected agent task with references resolved",
    "interpretation_notes": [
        "what was corrected or clarified",
        "what references were resolved"
    ],
    "success_criteria": [
        "specific measurable outcome 1",
        "specific measurable outcome 2"
    ]
}}

RULES:
- If the agent task is already clear and unambiguous, return it as-is with empty notes
- Be conservative - only make changes you're confident about
- Focus on making the agent task actionable and unambiguous
- Success criteria should be specific and verifiable

OUTPUT ONLY JSON. NO OTHER TEXT."""

            # Call LLM
            response = await self.llm_model.generate_response(interpretation_prompt, max_tokens=500)
            
            # Parse JSON response
            import json
            try:
                result = json.loads(response.strip())
            except json.JSONDecodeError as e:
                preview = (response or "").strip().replace("\n", "\\n")[:300]
                self.logger.warning(
                    "Intelligent interpretation returned non-JSON; falling back. error=%s preview=%r",
                    e,
                    preview,
                )
                return None
            
            # Validate required fields
            if 'interpreted_agent_task' not in result:
                self.logger.warning("LLM interpretation missing 'interpreted_agent_task' field")
                return None
            
            # Ensure lists exist
            if 'interpretation_notes' not in result:
                result['interpretation_notes'] = []
            if 'success_criteria' not in result:
                result['success_criteria'] = []
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in intelligent interpretation: {e}", exc_info=True)
            return None 