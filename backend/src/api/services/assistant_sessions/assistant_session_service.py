import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

from ..transcription.backends.huggingface_service import HuggingFaceTranscriptionService
from ..ocr.ocr_service import OCRService
from api.core.models.model_invocation import call_model_with_prompt
from api.services.model_usage_service import ModelUsageService
from ...core.services.model_service import get_model_service
from ...core.models.model_types import ModelCapability
from .context_enhancers import AssistantSessionContextEnhancer

logger = logging.getLogger(__name__)

class AssistantSessionService:
    """
    Orchestrates the AssistantSession flow: screen capture + OCR, audio transcription, and suggestion generation.
    Uses HuggingFaceTranscriptionService for transcription and OCRService for OCR.
    Session management links OCR and audio steps.
    """
    def __init__(self, ocr_service: Optional[OCRService] = None, transcription_service: Optional[HuggingFaceTranscriptionService] = None, model_usage_service: Optional[ModelUsageService] = None):
        self.ocr_service = ocr_service or OCRService()
        
        # Use provided transcription service or log warning about creating new instance
        if transcription_service:
            self.transcription_service = transcription_service
        else:
            logger.warning("No transcription service provided to AssistantSessionService, creating new instance")
            self.transcription_service = HuggingFaceTranscriptionService()
            
        self.model_usage_service = model_usage_service or ModelUsageService(get_model_service())
        self.context_enhancer = AssistantSessionContextEnhancer()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_expiry = timedelta(minutes=10)

    def _generate_session_id(self) -> str:
        return str(uuid.uuid4())

    async def _call_model_with_fallback(self, model, **call_kwargs) -> tuple:
        """Call call_model_with_prompt, retrying once against the local fallback
        model if the first attempt fails with a completely-unreachable error.

        Returns (suggestion_text, fallback_model_id_used_or_None).
        """
        try:
            suggestion = await call_model_with_prompt(model, **call_kwargs)
            return suggestion, None
        except Exception as first_error:
            from api.services.model_usage_service import is_model_unreachable_error
            if not is_model_unreachable_error(first_error):
                raise
            fallback_model = await self.model_usage_service.get_designated_local_fallback_model(
                {ModelCapability.REASONING}
            )
            if fallback_model is None:
                raise
            logger.warning(f"Reasoning model unreachable ({first_error}); retrying with local fallback")
            suggestion = await call_model_with_prompt(fallback_model, **call_kwargs)
            return suggestion, fallback_model.model_name

    def _cleanup_old_sessions(self):
        now = datetime.now()
        expired = [sid for sid, s in self.sessions.items() if now - s["created_at"] > self.session_expiry]
        for sid in expired:
            logger.info(f"Cleaning up expired session: {sid}")
            del self.sessions[sid]

    def capture_screen_and_extract_text(self, image_path: str, session_id: str) -> None:
        """
        Run OCR on the provided image path and store the result in the session.
        This method is intended to be called by the router using asyncio.to_thread.
        """
        print(f"🎤 [SERVICE] OCR method called for session {session_id}, image: {image_path}", flush=True)
        logger.info(f"[SERVICE] Running OCR for session: {session_id} on image: {image_path}")
        try:
            print(f"🎤 [SERVICE] Calling ocr_service.extract_text for session {session_id}", flush=True)
            ocr_result = self.ocr_service.extract_text(image_path)
            print(f"🎤 [SERVICE] OCR extraction completed for session {session_id}", flush=True)
            self.sessions[session_id]["ocr_result"] = ocr_result
            
            # Debug: log the full OCR result for debugging signature issues
            if hasattr(ocr_result, 'cleaned_text') and ocr_result.cleaned_text:
                full_text = ocr_result.cleaned_text
                logger.debug(f"[DEV][OCR FULL] session={session_id}, length={len(full_text)}")
                logger.debug(f"[DEV][OCR FULL] session={session_id}, text={full_text}")
            else:
                logger.warning(f"[SERVICE] OCR result missing cleaned_text for session: {session_id}")
            
            logger.info(f"[SERVICE] OCR completed for session: {session_id}")
        except Exception as e:
            logger.error(f"[SERVICE] OCR failed for session {session_id}: {e}")
            from ..ocr.ocr_models import OCRResult # Keep import here for now
            self.sessions[session_id]["ocr_result"] = OCRResult(
                status="error",
                error=f"OCR failed: {str(e)}",
                image_path=image_path,
                processing_time_ms=0
            )

    async def transcribe_audio(self, session_id: str, audio_data: bytes, context_info: Optional[dict] = None) -> Dict[str, Any]:
        """
        Transcribe audio using HuggingFaceTranscriptionService and store result in session.
        Returns transcription result.
        """
        if session_id not in self.sessions:
            logger.error(f"Session not found: {session_id}")
            raise ValueError("Session not found")
        # Ensure transcription model is loaded before transcribing
        if not self.transcription_service.is_model_loaded():
            logger.info(f"Loading transcription model for session: {session_id}")
            self.transcription_service.load_model()
        transcription = await self.transcription_service.transcribe(audio_data, context_info or {})
        self.sessions[session_id]["transcription"] = transcription
        return {"transcription": transcription}

    async def generate_suggestion(self, session_id: str, model_id: Optional[str] = None, additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a context-aware suggestion based on OCR and transcription results.
        Supports both full document and text selection-targeted suggestions.
        
        Args:
            session_id: Session identifier
            model_id: Optional specific model to use
            additional_context: Optional additional context (email content, file content, etc.)
        """
        session = self.sessions.get(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            raise ValueError("Session not found")
        
        ocr_text = session["ocr_result"].cleaned_text if hasattr(session["ocr_result"], 'cleaned_text') else ""
        transcription = session["transcription"]
        
        # Retrieve text selection context if available
        text_selection = session.get("text_selection")
        has_selection_context = session.get("has_selection_context", False)
        
        # Extract app name from session data for application-first context detection
        app_name = None
        if "capture_result" in session and isinstance(session["capture_result"], dict):
            app_name = session["capture_result"].get("app_name")
        if not app_name and "app_info" in session:
            app_name = session["app_info"].get("app_name") if isinstance(session["app_info"], dict) else None
        
        logger.info(f"[SERVICE] Detected app: {app_name or 'Unknown'} for session {session_id}")
        
        # Check if additional context is provided - if so, use generic prompt building
        if additional_context:
            logger.info(f"[SERVICE] Using additional context for session {session_id}: {list(additional_context.keys())}")
            
            # Build generic prompt with additional context
            prompt_parts = [
                "You are an AI assistant helping with content creation and writing. The user has provided some content from their screen and a specific instruction.",
                "",
                f"CURRENT APPLICATION: {app_name or 'Unknown'}",
                "",
                "SCREEN CONTENT:",
                ocr_text,
                ""
            ]
            
            # Add additional context sections generically
            for context_key, context_value in additional_context.items():
                prompt_parts.extend([
                    f"ADDITIONAL CONTEXT ({context_key.upper().replace('_', ' ')}):",
                    "=" * 40,
                    str(context_value)[:2000] + ("..." if len(str(context_value)) > 2000 else ""),
                    "",
                    ""
                ])
            
            prompt_parts.extend([
                f'USER INSTRUCTION: "{transcription}"',
                "",
                "Please provide a helpful response that follows the user's instruction using all the provided context. Be concise but complete."
            ])
            
            enhanced_prompt = "\n".join(prompt_parts)
            enhancement_result = {
                "enhanced_prompt": enhanced_prompt,
                "context_type": "additional_context",
                "metadata": {"additional_context_keys": list(additional_context.keys())}
            }
        
        elif has_selection_context and text_selection:
            logger.info(f"[SERVICE] Using text selection context for session {session_id}: '{text_selection.get('selected_text', '')[:50]}...'")
            # Use context enhancer with text selection data and app name
            enhancement_result = await self.context_enhancer.enhance_suggestion_context(
                content=ocr_text, 
                instruction=transcription,
                text_selection=text_selection,
                app_name=app_name
            )
        else:
            logger.info(f"[SERVICE] Using full document context for session {session_id}")
            # Use context enhancer with standard full document approach and app name
            enhancement_result = await self.context_enhancer.enhance_suggestion_context(
                content=ocr_text, 
                instruction=transcription,
                app_name=app_name
            )
        
        # Load reasoning model
        model = await self.model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id
        )
        
        if not model:
            logger.warning("No suitable model found for AssistantSession")
            suggestion = "[Error: No suitable model found for AssistantSession.]"
        else:
            # Always enable web search and let the model decide when to use it intelligently
            logger.info(f"Web search available for instruction: '{transcription[:50]}...'")
            
            # Use enhanced prompt from context enhancer with web search available
            suggestion, fallback_model_id = await self._call_model_with_fallback(
                model,
                prompt=enhancement_result["enhanced_prompt"],
                system_prompt=enhancement_result.get("system_prompt"),
                enable_web_search=True,
            )
            if fallback_model_id:
                session["fallback_model_used"] = fallback_model_id
            
            logger.info(f"Generated AssistantSession for instruction: '{transcription[:50]}...'")
        
        # Store results with context information for debugging/analysis
        session["suggestion"] = suggestion
        session["context_type"] = enhancement_result["context_type"]
        session["metadata"] = enhancement_result["metadata"]
        session["selection_mode"] = "targeted" if has_selection_context else "full_document"
        
        return {"suggestion": suggestion}

    async def process_audio_for_suggestion(self, session_id: str, audio_data: bytes, model_id: Optional[str] = None, context_info: Optional[dict] = None, additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Full flow: transcribe audio and generate suggestion for a session.
        Returns transcription and suggestion.
        """
        print(f"🎤 [ASSISTANT_SESSION_SERVICE] Starting process_audio_for_suggestion for session {session_id}", flush=True)
        logger.warning(f"🎤 [ASSISTANT_SESSION_SERVICE] Starting process_audio_for_suggestion for session {session_id}")
        transcription_result = await self.transcribe_audio(session_id, audio_data, context_info)
        print(f"🎤 [ASSISTANT_SESSION_SERVICE] Transcription complete, calling generate_suggestion for session {session_id}", flush=True)
        logger.warning(f"🎤 [ASSISTANT_SESSION_SERVICE] Transcription complete, calling generate_suggestion for session {session_id}")
        suggestion_result = await self.generate_suggestion(session_id, model_id, additional_context)
        print(f"🎤 [ASSISTANT_SESSION_SERVICE] Suggestion generated for session {session_id}", flush=True)
        logger.warning(f"🎤 [ASSISTANT_SESSION_SERVICE] Suggestion generated for session {session_id}")
        return {
            "transcription": transcription_result["transcription"],
            "suggestion": suggestion_result["suggestion"]
        }

    async def process_refinement_audio(self, session_id: str, audio_data: bytes, model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process refinement audio for existing session without new OCR.
        Uses initial context + previous output + new instruction.
        """
        session = self.sessions.get(session_id)
        if not session:
            logger.error(f"Refinement session not found: {session_id}")
            raise ValueError("Session not found or expired")
        
        if not session.get("refinement_mode", False):
            # Convert to refinement mode
            session["initial_transcription"] = session.get("transcription", "")
            session["initial_suggestion"] = session.get("suggestion", "")
            session["refinement_mode"] = True
            session["iteration_count"] = 0
            logger.info(f"[SERVICE] Session {session_id} converted to refinement mode")
        
        # Transcribe new audio
        if not self.transcription_service.is_model_loaded():
            logger.info(f"Loading transcription model for refinement session: {session_id}")
            self.transcription_service.load_model()
        
        new_transcription = await self.transcription_service.transcribe(audio_data, {})
        session["current_transcription"] = new_transcription
        session["iteration_count"] += 1
        
        logger.info(f"[SERVICE] Processing refinement {session['iteration_count']} for session {session_id}")
        
        # Build refinement prompt
        refinement_prompt = await self._build_refinement_prompt(session)
        
        # Generate refined suggestion
        model = await self.model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id
        )
        
        if not model:
            logger.warning("No suitable model found for refinement")
            refined_suggestion = "[Error: No suitable model found for refinement.]"
        else:
            refined_suggestion, fallback_model_id = await self._call_model_with_fallback(
                model,
                prompt=refinement_prompt,
                enable_web_search=True,
            )
            if fallback_model_id:
                session["fallback_model_used"] = fallback_model_id
            logger.info(f"Generated refinement suggestion for session {session_id}")
        
        session["current_suggestion"] = refined_suggestion
        
        return {
            "transcription": new_transcription,
            "suggestion": refined_suggestion,
            "iteration_count": session["iteration_count"]
        }

    async def process_refinement_text(self, session_id: str, instruction_text: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """Text-instruction analog of :meth:`process_refinement_audio`.

        Mirrors the audio refinement flow exactly, just without the
        transcribe step: convert the session to refinement mode on first
        call, store the typed instruction as ``current_transcription``
        (so the existing ``_build_refinement_prompt`` consumes it via
        the same dict lookup the audio path uses), then run the
        reasoning model and return the new iteration count.

        Refinement does not have a "no input" modality -- there is
        nothing to refine toward without an instruction, so an empty
        string raises rather than substituting a default.
        """
        if not instruction_text or not instruction_text.strip():
            raise ValueError("Refinement requires a non-empty instruction")

        session = self.sessions.get(session_id)
        if not session:
            logger.error(f"Refinement session not found: {session_id}")
            raise ValueError("Session not found or expired")

        if not session.get("refinement_mode", False):
            session["initial_transcription"] = session.get("transcription", "")
            session["initial_suggestion"] = session.get("suggestion", "")
            session["refinement_mode"] = True
            session["iteration_count"] = 0
            logger.info(f"[SERVICE] Session {session_id} converted to refinement mode (text)")

        instruction = instruction_text.strip()
        session["current_transcription"] = instruction
        session["iteration_count"] += 1

        logger.info(f"[SERVICE] Processing text refinement {session['iteration_count']} for session {session_id}")

        refinement_prompt = await self._build_refinement_prompt(session)

        model = await self.model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=model_id
        )

        if not model:
            logger.warning("No suitable model found for text refinement")
            refined_suggestion = "[Error: No suitable model found for refinement.]"
        else:
            refined_suggestion, fallback_model_id = await self._call_model_with_fallback(
                model,
                prompt=refinement_prompt,
                enable_web_search=True,
            )
            if fallback_model_id:
                session["fallback_model_used"] = fallback_model_id
            logger.info(f"Generated text refinement suggestion for session {session_id}")

        session["current_suggestion"] = refined_suggestion

        return {
            "transcription": instruction,
            "suggestion": refined_suggestion,
            "iteration_count": session["iteration_count"]
        }

    async def _build_refinement_prompt(self, session: Dict[str, Any]) -> str:
        """Build prompt for refinement using initial context + previous output + new instruction."""
        initial_request = session.get("initial_transcription", "")
        previous_output = session.get("initial_suggestion") if session["iteration_count"] == 1 else session.get("current_suggestion", "")
        new_request = session.get("current_transcription", "")
        ocr_text = session["ocr_result"].cleaned_text if hasattr(session["ocr_result"], 'cleaned_text') else ""
        
        # Extract app context if available
        app_name = None
        if "text_selection" in session and session["text_selection"]:
            app_name = session["text_selection"].get("application_name")
        
        # Use context enhancer with refinement context
        return await self.context_enhancer.enhance_refinement_context(
            initial_context=ocr_text,
            initial_request=initial_request,
            previous_output=previous_output,
            refinement_request=new_request,
            app_name=app_name
        ) 