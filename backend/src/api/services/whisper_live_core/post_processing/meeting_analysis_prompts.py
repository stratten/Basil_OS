"""
Prompt builder for meeting analysis with context-enhanced templates.

Provides specialized prompts for each analysis mode following defensive
prompting patterns from AssistantSession enhancers.
"""
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class MeetingAnalysisPromptBuilder:
    """
    Builds context-enhanced prompts for various meeting analysis modes.
    
    Follows defensive prompting patterns to ensure structured, accurate outputs
    while preventing hallucination and maintaining speaker attribution.
    """
    
    def __init__(self):
        """Initialize the prompt builder."""
    
    def build_action_items_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Build prompt for extracting action items from meeting transcript.
        
        Args:
            transcript: Full meeting transcript with speaker labels and timestamps
            meeting_metadata: Meeting context (name, participants, duration, etc.)
            custom_instructions: Optional user-provided instructions
            
        Returns:
            Context-enhanced prompt for action item extraction
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        custom_section = self._build_custom_instructions_section(custom_instructions)
        
        prompt = f"""You are an expert meeting analyst specializing in extracting actionable tasks and commitments.

{metadata_section}

TRANSCRIPT:
{transcript}

YOUR TASK:
Extract all action items, tasks, commitments, and follow-up items mentioned in this meeting. For each action item, identify:
1. The specific task or action to be taken
2. Who is assigned or responsible (if mentioned)
3. Any deadline or timeframe (if mentioned)
4. Priority level if indicated (high, medium, low)
5. The exact timestamp and speaker who mentioned it
6. Relevant context from the conversation

EXTRACTION CRITERIA:
- Include explicit commitments ("I'll do X", "We need to Y")
- Include implicit tasks from discussion ("Someone should...", "We should...")
- Include follow-up items ("Let's check back on...", "We'll revisit...")
- DO NOT invent or infer action items that weren't discussed
- DO NOT include general discussion points that aren't actionable

OUTPUT FORMAT:
Return one JSON object with an "items" array:
{{"items": [{{
  "task": "Clear description of the action item",
  "assigned_to": "Speaker name or null if not mentioned",
  "deadline": "Deadline or timeframe if mentioned, null otherwise",
  "priority": "high/medium/low if indicated, null otherwise",
  "context": "Relevant excerpt showing where this was mentioned",
  "timestamp": 123.45,
  "speaker": "Speaker who mentioned it"
}}]}}

CRITICAL RULES:
- Return ONLY the JSON object, no additional commentary
- Use exact speaker names from the transcript
- Include actual timestamps from the transcript
- If no action items are found, return {{"items": []}}
- Do not fabricate information not present in the transcript
{custom_section}

JSON OUTPUT:"""
        
        return prompt

    def build_suggested_actions_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        action_items: Optional[List[Dict[str, Any]]] = None,
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Build prompt for identifying grouped meeting To-Do candidates.

        Args:
            transcript: Full meeting transcript with speaker labels and timestamps
            meeting_metadata: Meeting context (name, participants, duration, etc.)
            action_items: Optional action items already extracted from the meeting
            custom_instructions: Optional user-provided instructions

        Returns:
            Context-enhanced prompt for classified To-Do candidates
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        custom_section = self._build_custom_instructions_section(custom_instructions)
        action_items_json = json.dumps(action_items or [], indent=2)

        # Prefer the dynamically-built capability digest (live tool families +
        # connected integrations). Fall back to a static list if unavailable.
        capabilities_section = meeting_metadata.get("capability_digest") or (
            "KNOWN BASIL CAPABILITIES:\n"
            "- Draft emails or messages, but do not claim to send unless the user approves later.\n"
            "- Create reminders, notes, calendar events, or simple app automations through macOS automation.\n"
            "- Help with documents, files, summaries, searches, and research.\n"
            "- Help with project or developer work through approved file/shell workflows.\n"
            "- Run autonomous work at a future time via its scheduling capability.\n"
            "- Ask for missing information when a task lacks recipients, dates, file names, permissions, or target apps."
        )

        prompt = f"""You are Basil's meeting follow-up planner. You produce a review
queue of durable To-Do candidates, not a list of every statement that sounds
like a task. You do not execute anything yourself. Each candidate may be a
tracking-only To-Do or may include a concrete agent action that the user can
approve later.

{metadata_section}

{capabilities_section}

EXTRACTED ACTION ITEMS:
{action_items_json}

TRANSCRIPT:
{transcript}

YOUR TASK:
Classify each potential follow-up from the extracted action items and transcript.
Return one candidate only for a concrete, unresolved outcome that the user should
retain as a durable To-Do. Prefer using the extracted action items above. If they
are empty, infer conservative candidates directly from the transcript.

Do not return a candidate for work completed, closed, billed, scheduled, sent,
created, or explicitly resolved during the meeting. Do not return an explanatory
card for completed, informational, or otherwise non-actionable material. Mark
such material with disposition "completed_or_resolved" or "non_actionable" so
Basil can discard it.

Group checklist-level tasks into one candidate when they serve the same
deliverable, system change, recipient, deadline, or workstream. For a grouped
candidate, write one concise title in source_task and use ordered Markdown bullets
in suggested_agent_task for the component steps. Do not split one cohesive
deliverable into separate candidates merely because the transcript states its
checklist items separately.

Use execution_mode "agent_assisted" whenever Basil can make useful, safe initial
progress after approval, even when follow-up details remain unknown. This includes
researching options, drafting, outlining a plan, preparing a document, organizing
information, inspecting available files, or working through a listed connection.
Missing inputs should be listed in missing_information; they do not make a
candidate To-Do-only when Basil can begin research, create a draft, or ask for the
needed clarification during execution. Use "todo_only" only when the entire
outcome requires an action Basil cannot productively begin, such as the user's
personal decision, attendance, physical work, or a relationship-specific
conversation. Every retained candidate must use disposition "todo_candidate".

When a follow-up targets a system that is reachable through one of the CURRENT
CONNECTIONS listed above, frame suggested_agent_task as Basil performing that
work THROUGH that connection, naming the connection explicitly. This applies
regardless of timing.

Match on the connection's served system, which may be named in ANY part of its
block - the friendly name, server name, tool names/descriptions, OR its
"guidance"/instructions line. The served system is frequently stated ONLY in the
guidance line while the server and tool names are generic/branded, so read the
guidance before deciding a connection is irrelevant. Example: a connection whose
guidance says it "performs Salesforce org changes" IS the correct home for a
Salesforce configuration task, even though its tool names never contain the word
"Salesforce".

Prefer the connection that can DO the domain work over one that merely TRACKS
it. Do NOT file a task into a generic issue tracker / project tool (e.g. Linear)
when another connected integration can actually perform the underlying work in
its own system; route it to the integration that does the work, and use a
tracker only when no connection can perform the work or the user explicitly
wants it tracked. Never state that Basil lacks access to a system when a
connection above serves that system - name and use that connection instead.

Likewise, do NOT downgrade such an item to a documentation/spec task for a human
(e.g. "draft a spec for the Salesforce developer") when a connected integration
can do the work directly; only fall back to drafting when no connection serves
that system or the work is inherently a human deliverable.

When a follow-up should happen at a specific future time AND maps to a
capability or connected integration above, set capability_type to
"scheduled_agent_task" and phrase suggested_agent_task as a scheduled delegated
instruction: state the date/time with timezone, the concrete action, and that
the agent should perform and monitor it. Do NOT downgrade such an item to a
plain "reminder" when Basil itself can do the work (e.g. triggering a Salesforce
export through a connected integration like Speakeasy).

CAPABILITY TYPES:
- todo
- email_draft
- calendar_event
- reminder
- note
- document_work
- research
- file_operation
- project_work
- automation
- scheduled_agent_task
- needs_clarification

OUTPUT FORMAT:
Return one JSON object with an "items" array:
{{"items": [{{
  "source_action_item_indexes": [0, 1, 2],
  "source_action_item_index": 0,
  "source_task": "Research viable encryption key management and rotation options",
  "source_context": "[02:03] Speaker 1: First exact supporting transcript line.\n[02:05] Speaker 2: Second exact supporting transcript line when the proposal depends on an exchange.",
  "source_timestamp": 123.0,
  "source_speaker": null,
  "suggested_agent_task": "Research viable encryption key management and rotation providers and strategies. Summarize credible options, trade-offs, and questions requiring the user's policy decision before the review with Avram.",
  "capability_type": "research",
  "confidence": 0.85,
  "why_basil_can_help": "Short explanation of why this unresolved outcome should be retained",
  "missing_information": ["specific rotation policy requirements"],
  "requires_user_confirmation": true,
  "disposition": "todo_candidate",
  "execution_mode": "agent_assisted"
}}]}}

CRITICAL RULES:
- Return ONLY the JSON object, no additional commentary.
- Do NOT include an id; Basil will generate stable proposal ids.
- Every proposal must be grounded in the transcript or extracted action items.
- Set source_context to one or more complete transcript lines copied verbatim from TRANSCRIPT, including every quoted line's bracketed timestamp and speaker label. Never summarize, paraphrase, correct grammar, combine wording, or add text that is not present in those lines.
- Include multiple source_context lines in chronological order when a back-and-forth exchange or series of iterations materially informs the proposal. Include only the lines needed to let the user judge whether the proposed task reflects the meeting's intent.
- Set source_timestamp to the timestamp in seconds of the first source_context line. Set source_speaker to that line's exact speaker label only when every quoted line has the same speaker; otherwise set source_speaker to null.
- Do NOT propose automatic execution.
- When execution_mode is "agent_assisted", make suggested_agent_task a self-contained instruction that names the user and any apps or integrations explicitly; do NOT use "you" because a separate delegate has no chat context.
- When execution_mode is "todo_only", make suggested_agent_task a concise To-Do description with any grouped component steps. Do not use todo_only merely because the candidate needs clarification or benefits from user edits before Start now.
- Write "why_basil_can_help" addressed to the user in the second person ("you"/"your").
- If an item is too vague, use capability_type \"needs_clarification\" and list missing_information.
- Do not fabricate recipients, dates, file names, or external system access.
{custom_section}

JSON OUTPUT:"""

        return prompt
    
    def build_summary_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Build prompt for generating a concise meeting summary.
        
        Args:
            transcript: Full meeting transcript
            meeting_metadata: Meeting context
            custom_instructions: Optional user instructions
            
        Returns:
            Context-enhanced prompt for summary generation
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        custom_section = self._build_custom_instructions_section(custom_instructions)
        
        prompt = f"""You are an expert meeting analyst specializing in creating concise, accurate meeting summaries.

{metadata_section}

TRANSCRIPT:
{transcript}

YOUR TASK:
Create a comprehensive yet concise summary of this meeting that captures:
1. Main topics discussed
2. Key points raised by each participant
3. Important outcomes or conclusions
4. Overall meeting flow and structure

SUMMARY STRUCTURE:
Use this format:

## Overview
[2-3 sentence high-level summary of the meeting's purpose and outcome]

## Key Discussion Points
[Bulleted list of main topics discussed, with brief context for each]

## Participant Contributions
[Brief summary of each speaker's main points or contributions]

## Outcomes
[Key takeaways, conclusions, or results from the meeting]

GUIDELINES:
- Be objective and factual - only include what was actually discussed
- Maintain speaker attribution for important points
- Keep the summary concise but comprehensive (aim for 300-500 words)
- Use professional business language
- Focus on substance over process details
- DO NOT invent or infer information not present in the transcript
{custom_section}

OUTPUT FORMAT:
Return one JSON object with exactly this structure:
{{"markdown": "Complete summary using the required Markdown headings"}}

CRITICAL RULES:
- Return ONLY the JSON object, no markdown fence or commentary outside it
- Put the complete Overview, Key Discussion Points, Participant Contributions, and Outcomes Markdown in "markdown"

JSON OUTPUT:"""
        
        return prompt
    
    def build_decisions_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Build prompt for identifying key decisions made in the meeting.
        
        Args:
            transcript: Full meeting transcript
            meeting_metadata: Meeting context
            custom_instructions: Optional user instructions
            
        Returns:
            Context-enhanced prompt for decision extraction
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        custom_section = self._build_custom_instructions_section(custom_instructions)
        
        prompt = f"""You are an expert meeting analyst specializing in identifying and documenting key decisions.

{metadata_section}

TRANSCRIPT:
{transcript}

YOUR TASK:
Identify all significant decisions made during this meeting. For each decision:
1. What was decided
2. Why it was decided (rationale, if discussed)
3. Who made or approved the decision
4. When it was decided (timestamp)
5. Expected impact or implications (if mentioned)
6. Relevant context from the conversation

DECISION CRITERIA:
- Include explicit decisions ("We're going with option X", "We've decided to...")
- Include consensus agreements ("Everyone agrees...", "Let's move forward with...")
- Include leadership directives ("I'm deciding...", "We'll proceed with...")
- DO NOT include open questions or items still under discussion
- DO NOT include minor procedural decisions unless significant

OUTPUT FORMAT:
Return one JSON object with an "items" array:
{{"items": [{{
  "decision": "Clear statement of what was decided",
  "rationale": "Reasoning behind the decision (or null)",
  "decided_by": "Person or group who made the decision (or null)",
  "timestamp": 123.45,
  "context": "Relevant excerpt showing the decision",
  "impact": "Expected impact or implications (or null)"
}}]}}

CRITICAL RULES:
- Return ONLY the JSON object, no additional commentary
- Use exact speaker names and timestamps from the transcript
- Distinguish between final decisions and ongoing discussions
- If no clear decisions were made, return {{"items": []}}
- Do not fabricate decisions not explicitly made in the meeting
{custom_section}

JSON OUTPUT:"""
        
        return prompt
    
    def build_questions_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Build prompt for extracting questions and answers.
        
        Args:
            transcript: Full meeting transcript
            meeting_metadata: Meeting context
            custom_instructions: Optional user instructions
            
        Returns:
            Context-enhanced prompt for Q&A extraction
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        custom_section = self._build_custom_instructions_section(custom_instructions)
        
        prompt = f"""You are an expert meeting analyst specializing in extracting questions and answers.

{metadata_section}

TRANSCRIPT:
{transcript}

YOUR TASK:
Extract all significant questions asked during the meeting along with their answers. For each Q&A pair:
1. The question that was asked
2. The answer that was provided
3. Who asked the question
4. Who answered it
5. Timestamp when the question was asked
6. Whether the question was fully answered
7. Full conversation context

Q&A CRITERIA:
- Include explicit questions (marked with ? or phrased as questions)
- Include rhetorical questions that received substantive answers
- Include implied questions that prompted explanations
- Pair questions with their most direct answers
- Note if a question was left unanswered or partially answered
- DO NOT include purely procedural questions ("Can everyone hear me?")

OUTPUT FORMAT:
Return one JSON object with an "items" array:
{{"items": [{{
  "question": "The question that was asked",
  "answer": "The answer that was provided",
  "asker": "Speaker who asked (or null)",
  "responder": "Speaker who answered (or null)",
  "timestamp": 123.45,
  "context": "Full conversation excerpt including Q&A",
  "resolved": true
}}]}}

CRITICAL RULES:
- Return ONLY the JSON object, no additional commentary
- Use exact speaker names and timestamps
- Set "resolved" to false if question wasn't fully answered
- Include context showing both question and answer
- If no Q&A pairs are found, return {{"items": []}}
{custom_section}

JSON OUTPUT:"""
        
        return prompt
    
    def build_sentiment_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Build prompt for analyzing meeting sentiment and engagement.
        
        Args:
            transcript: Full meeting transcript
            meeting_metadata: Meeting context
            custom_instructions: Optional user instructions
            
        Returns:
            Context-enhanced prompt for sentiment analysis
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        custom_section = self._build_custom_instructions_section(custom_instructions)
        
        prompt = f"""You are an expert meeting analyst specializing in sentiment and engagement analysis.

{metadata_section}

TRANSCRIPT:
{transcript}

YOUR TASK:
Analyze the overall sentiment, tone, and engagement level of this meeting. Provide:
1. Overall meeting sentiment (positive, neutral, negative)
2. Sentiment score (-1.0 to 1.0)
3. Engagement level (high, medium, low)
4. Per-speaker sentiment breakdown
5. Key positive moments
6. Key negative or tense moments
7. Tone indicators observed

ANALYSIS GUIDELINES:
- Assess both explicit sentiment (word choice, tone) and implicit sentiment (agreement/disagreement patterns)
- Consider energy level, enthusiasm, and participation
- Note conflicts, tensions, or disagreements
- Identify collaborative vs. contentious dynamics
- Recognize formal vs. casual tone
- Base analysis ONLY on observable linguistic cues in the transcript

OUTPUT FORMAT:
Return one JSON object with an "analysis" value using this structure:
{{"analysis": {{
  "overall_sentiment": "positive|neutral|negative",
  "sentiment_score": 0.5,
  "engagement_level": "high|medium|low",
  "speaker_sentiments": {{
    "Speaker Name": {{
      "sentiment": "positive|neutral|negative",
      "engagement": "high|medium|low",
      "key_contributions": "Brief summary of their participation"
    }}
  }},
  "positive_moments": [
    {{"timestamp": 123.45, "description": "What happened", "context": "Relevant excerpt"}}
  ],
  "negative_moments": [
    {{"timestamp": 234.56, "description": "What happened", "context": "Relevant excerpt"}}
  ],
  "tone_indicators": ["collaborative", "formal", "technical", "etc"]
}}}}

CRITICAL RULES:
- Return ONLY the outer JSON object with the analysis value, no additional commentary
- Base sentiment on actual linguistic evidence from the transcript
- Do not over-interpret or read intentions not evident in the text
- Use timestamps and speaker names from the transcript
- If insufficient data for sentiment analysis, note limitations in the output
{custom_section}

JSON OUTPUT:"""
        
        return prompt
    
    def build_custom_prompt(
        self,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: str
    ) -> str:
        """
        Build prompt for custom user-defined analysis.
        
        Args:
            transcript: Full meeting transcript
            meeting_metadata: Meeting context
            custom_instructions: User's custom analysis request
            
        Returns:
            Context-enhanced prompt for custom analysis
        """
        metadata_section = self._build_metadata_section(meeting_metadata)
        
        prompt = f"""You are an expert meeting analyst helping with a custom analysis request.

{metadata_section}

TRANSCRIPT:
{transcript}

CUSTOM ANALYSIS REQUEST:
{custom_instructions}

YOUR TASK:
Analyze the meeting transcript according to the user's specific request above. 

GUIDELINES:
- Address the user's request directly and comprehensively
- Base your analysis entirely on the transcript content
- Include specific references, timestamps, and speaker attributions where relevant
- Organize your response clearly and logically
- If the request asks for structured data, provide it in an appropriate format
- If the transcript doesn't contain information needed for the analysis, state this clearly
- DO NOT invent or infer information not present in the transcript

CRITICAL RULES:
- Provide a complete, professional analysis
- Use evidence from the transcript to support your points
- Maintain objectivity and accuracy
- If the request is unclear or cannot be fulfilled, explain why

OUTPUT FORMAT:
Return one JSON object with exactly this structure:
{{"content": "Complete evidence-grounded response to the custom request"}}

CRITICAL OUTPUT RULES:
- Return ONLY the JSON object, no markdown fence or commentary outside it
- Preserve useful Markdown inside "content"

JSON OUTPUT:"""
        
        return prompt
    
    def _build_metadata_section(self, meeting_metadata: Dict[str, Any]) -> str:
        """Build formatted metadata section for prompts.

        When an identity block is provided it is prepended so every analysis
        mode knows who the user is (the first-person framing), preventing the
        model from treating the user as a third-party speaker.
        """
        lines = ["MEETING CONTEXT:"]
        
        if meeting_metadata.get("name"):
            lines.append(f"- Meeting: {meeting_metadata['name']}")
        
        if meeting_metadata.get("purpose"):
            lines.append(f"- Purpose: {meeting_metadata['purpose']}")
        
        if meeting_metadata.get("participants"):
            participants = meeting_metadata["participants"]
            if participants:
                lines.append(f"- Participants: {', '.join(participants)}")
        
        if meeting_metadata.get("duration"):
            duration = meeting_metadata["duration"]
            mins = int(duration / 60)
            secs = int(duration % 60)
            lines.append(f"- Duration: {mins}m {secs}s")
        
        if meeting_metadata.get("speaker_count"):
            lines.append(f"- Number of speakers: {meeting_metadata['speaker_count']}")
        
        context_section = "\n".join(lines)

        identity_block = meeting_metadata.get("identity_block")
        if identity_block:
            return f"{identity_block}\n\n{context_section}"
        return context_section
    
    def _build_custom_instructions_section(self, custom_instructions: Optional[str]) -> str:
        """Build custom instructions section if provided."""
        if not custom_instructions:
            return ""
        
        return f"""
ADDITIONAL INSTRUCTIONS FROM USER:
{custom_instructions}

Consider these instructions when performing the analysis above."""
    
