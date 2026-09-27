"""
Meeting analysis processor with LLM-powered analysis modes.

Orchestrates analysis execution across multiple modes including action items,
summaries, decisions, questions, sentiment, and custom analysis.
"""
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime

from .meeting_analysis_models import (
    AnalysisMode,
    AnalysisModeFailure,
    AnalysisSafetyOmission,
    AnalysisProgress,
    MeetingActionProposal,
    MeetingAnalysisResult,
    SuggestedActionDraft,
    build_action_proposals,
)
from .meeting_analysis_prompts import MeetingAnalysisPromptBuilder
from .meeting_analysis_context import (
    build_capability_digest,
    build_identity_block,
)
from .meeting_analysis_executor import MeetingAnalysisExecutor
from .meeting_transcript_utils import (
    count_unique_speakers,
    get_transcript_duration,
    parse_iso_to_epoch as _parse_iso_to_epoch,
)
from .transcript_merger import load_transcript_from_file, merge_session_transcripts
from api.services.meetings.meeting_recorder import MeetingMetadata, MeetingRecorder
from api.services.model_usage_service import ModelUsageService
from api.dependencies import get_model_service
from api.core.models.model_types import ModelCapability
from api.core.models.model_invocation import StructuredModelOutputError
from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile

logger = logging.getLogger(__name__)


class MeetingAnalyzer:
    """
    Orchestrates LLM-powered analysis of meeting transcripts.
    
    Supports multiple analysis modes with progress tracking and structured output.
    """
    
    def __init__(self, meeting_id: str, model_id: Optional[str] = None):
        """
        Initialize meeting analyzer.
        
        Args:
            meeting_id: UUID of the meeting to analyze
            model_id: Optional specific model ID to use (defaults to user's reasoning preference)
        """
        self.meeting_id = meeting_id
        self.model_id = model_id
        
        # Get meeting directory and paths
        self.meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        self.transcript_path = self.meeting_dir / "transcript.json"
        # analysis_path will be generated dynamically with timestamp when saving
        # Filename of the most recently saved analysis (for the analyze websocket).
        self.saved_analysis_filename: Optional[str] = None
        
        # Initialize components
        self.prompt_builder = MeetingAnalysisPromptBuilder()
        
        # State
        self.transcript: Optional[Dict[str, Any]] = None
        self.metadata: Optional[MeetingMetadata] = None
        self.model: Any = None

        # First-person identity + capability context for the prompts. Populated
        # once per run in analyze() so the (sync) prompt builder can read them.
        self._identity_block = ""
        self._capability_digest = ""
        # Audio-source labels captured at transcript load so the identity block can bind the user's mic track to "you".
        self._member_sources: List[Tuple[str, bool]] = []
        self._single_source: Optional[str] = None
        self._structured_output_enforcement: Dict[str, List[str]] = {}
        self._safety_omissions: List[AnalysisSafetyOmission] = []
        # Tracks whether any analysis mode has produced a successful model
        # response yet in this run; gates the one-time local fallback below
        # so it never fires once real progress has already been made.
        self._any_mode_succeeded = False
        self.fallback_model_used: Optional[str] = None
        
        logger.info(f"Initialized MeetingAnalyzer for meeting {meeting_id}")
    
    async def analyze(
        self,
        modes: List[str],
        custom_instructions: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> MeetingAnalysisResult:
        """
        Perform analysis on the meeting transcript.
        
        Args:
            modes: List of analysis modes to run
            custom_instructions: Optional custom instructions from user
            progress_callback: Optional callback for progress updates
            
        Returns:
            MeetingAnalysisResult with completed analyses
        """
        start_time = time.time()
        
        try:
            # Stage 1: Load transcript and metadata
            await self._send_progress(
                progress_callback,
                stage="loading",
                stage_progress=0.0,
                completed_modes=[],
                total_modes=len(modes),
                message="Loading transcript and initializing model..."
            )
            
            await self._load_transcript()
            await self._load_model()
            await self._load_identity_and_capabilities()
            
            await self._send_progress(
                progress_callback,
                stage="loading",
                stage_progress=1.0,
                completed_modes=[],
                total_modes=len(modes),
                message="Ready to analyze"
            )
            
            # Stage 2: Run each analysis mode
            modes = self._order_modes_for_dependencies(modes)
            results: Dict[str, Any] = {}
            completed_modes: List[str] = []
            failed_modes: List[AnalysisModeFailure] = []
            self._safety_omissions = []

            for mode in modes:
                mode_enum = AnalysisMode(mode)
                mode_label = mode_enum.value.replace("_", " ")

                await self._send_progress(
                    progress_callback,
                    stage=f"analyzing_{mode}",
                    stage_progress=0.0,
                    completed_modes=completed_modes,
                    total_modes=len(modes),
                    message=f"Analyzing: {mode_label.title()}...",
                    current_mode=mode
                )

                try:
                    mode_result = await self._analyze_mode(
                        mode_enum,
                        custom_instructions,
                        results,
                        progress_callback=progress_callback,
                        completed_modes=completed_modes,
                        total_modes=len(modes),
                    )
                except Exception as error:
                    failed_modes.append(self._build_mode_failure(mode_enum, error))
                    logger.error(
                        "Failed to analyze mode %s: %s",
                        mode_enum.value,
                        error,
                        exc_info=True,
                    )
                    await self._send_progress(
                        progress_callback,
                        stage=f"analyzing_{mode}",
                        stage_progress=1.0,
                        completed_modes=completed_modes,
                        total_modes=len(modes),
                        message=f"Failed {mode_label}; continuing with remaining analyses",
                        current_mode=mode,
                    )
                    continue

                results[mode] = mode_result
                completed_modes.append(mode)

                await self._send_progress(
                    progress_callback,
                    stage=f"analyzing_{mode}",
                    stage_progress=1.0,
                    completed_modes=completed_modes,
                    total_modes=len(modes),
                    message=f"Completed {len(completed_modes)} of {len(modes)} analyses"
                )

            # Stage 3: Combine results
            await self._send_progress(
                progress_callback,
                stage="complete",
                stage_progress=1.0,
                completed_modes=completed_modes,
                total_modes=len(modes),
                message="Analysis complete"
            )

            processing_time = time.time() - start_time

            analysis_result = self._build_analysis_result(
                modes,
                results,
                custom_instructions,
                processing_time,
                failed_modes,
                self._safety_omissions,
            )
            
            # Save analysis to disk
            await self._save_analysis(analysis_result)
            
            logger.info(
                f"Analysis completed for meeting {self.meeting_id}: "
                f"{len(modes)} modes in {processing_time:.1f}s"
            )
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"Analysis failed for meeting {self.meeting_id}: {e}", exc_info=True)
            raise
    
    async def _load_transcript(self) -> None:
        """
        Load meeting transcript from disk.

        If this meeting belongs to a session (mic + system audio share a
        session_id), the transcripts of all session members are merged into a
        single chronological transcript so analysis sees both sides of the
        conversation. Legacy meetings with no session_id (or sessions with a
        single member) fall back to loading just this meeting's transcript.
        """
        try:
            # Load metadata first so we can detect session grouping.
            self.metadata = MeetingRecorder.load_metadata(self.meeting_id)

            session_id = self.metadata.session_id if self.metadata else None
            members: List[Dict[str, Any]] = (
                self._gather_session_members(session_id) if session_id else []
            )

            if len(members) > 1:
                self.transcript = merge_session_transcripts(members)
                self._member_sources = [(m["source"], bool(m.get("is_microphone"))) for m in members]
                sources = ", ".join(m["source"] for m in members)
                logger.info(
                    f"Loaded merged session transcript with "
                    f"{len(self.transcript.get('segments', []))} segments from "
                    f"{len(members)} sources [{sources}] for session {session_id} "
                    f"(meeting {self.meeting_id})"
                )
            else:
                transcript_data = load_transcript_from_file(self.transcript_path)
                self.transcript = transcript_data
                self._single_source = self.metadata.audio_source if self.metadata else None
                logger.info(
                    f"Loaded transcript with {len(transcript_data.get('segments', []))} segments "
                    f"for meeting {self.meeting_id}"
                )

        except Exception as e:
            logger.error(f"Failed to load transcript: {e}")
            raise RuntimeError(f"Could not load transcript for meeting {self.meeting_id}: {e}")

    def _gather_session_members(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Find all meeting directories sharing the given session_id and load each
        member's transcript, tagged with its audio source.

        Returns a list of {"source": str, "segments": [...]} ordered by start
        time. Members without a usable transcript are skipped.
        """
        members: List[Dict[str, Any]] = []
        meetings_dir = Path.home() / ".basil" / "meetings"

        if not meetings_dir.exists():
            return members

        # Collect (dir, metadata) pairs whose session_id matches.
        member_entries = []
        for directory in meetings_dir.iterdir():
            if not directory.is_dir():
                continue
            metadata_path = directory / "metadata.json"
            if not metadata_path.exists():
                continue
            try:
                with open(metadata_path, 'r') as f:
                    member_metadata = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read metadata for {directory.name}: {e}")
                continue
            if member_metadata.get("session_id") == session_id:
                member_entries.append((directory, member_metadata))

        # Stable ordering by start time (both sources share the recording origin).
        member_entries.sort(key=lambda pair: pair[1].get("start_time") or "")

        # First pass: load each member and capture its absolute recording start
        # so cross-track start skew (e.g. the system tap opening ~1.3s after the
        # mic) can be corrected by shifting onto a shared session origin.
        loaded_members: List[Dict[str, Any]] = []
        for directory, member_metadata in member_entries:
            transcript_path = directory / "transcript.json"
            if not transcript_path.exists():
                continue
            try:
                transcript = load_transcript_from_file(transcript_path)
            except Exception as e:
                # Empty or invalid transcript (e.g. a silent source) - skip it.
                logger.warning(f"Skipping session member {directory.name}: {e}")
                continue

            is_microphone = (member_metadata.get("audio_source") or "").lower() == "microphone"
            source = member_metadata.get("audio_source") or ("Microphone" if is_microphone else "System Audio")
            loaded_members.append({
                "source": source,
                "is_microphone": is_microphone,
                "segments": transcript.get("segments", []),
                "_start_epoch": _parse_iso_to_epoch(member_metadata.get("start_time")),
            })

        # Compute the shared session origin (earliest known track start) and the
        # per-member offset onto it. Members lacking a parseable start_time get a
        # 0 offset, preserving prior behavior.
        known_starts = [m["_start_epoch"] for m in loaded_members if m["_start_epoch"] is not None]
        session_origin = min(known_starts) if known_starts else None

        for member in loaded_members:
            start_epoch = member.pop("_start_epoch")
            if session_origin is not None and start_epoch is not None:
                member["start_offset_seconds"] = max(0.0, start_epoch - session_origin)
            else:
                member["start_offset_seconds"] = 0.0
            members.append(member)

        return members
    
    async def _load_identity_and_capabilities(self) -> None:
        """Load first-person user identity and the agent capability digest once.

        Both are best-effort: any failure leaves the corresponding context empty
        so analysis proceeds without it rather than failing.
        """
        try:
            from api.core.knowledge.personalization_service import PersonalizationService

            profile = await PersonalizationService().get_user_profile()
            self._identity_block = build_identity_block(profile, member_sources=self._member_sources, single_source=self._single_source)
        except Exception as e:
            logger.warning(f"Could not load user profile for meeting analysis identity: {e}")
            self._identity_block = ""

        try:
            self._capability_digest = build_capability_digest()
        except Exception as e:
            logger.warning(f"Could not build capability digest for meeting analysis: {e}")
            self._capability_digest = ""

    async def _load_model(self) -> None:
        """Load the reasoning model for analysis."""
        try:
            model_service = get_model_service()
            model_usage_service = ModelUsageService(model_service)
            
            # Get model with reasoning capability
            self.model = await model_usage_service.get_model_for_task(
                capabilities={ModelCapability.REASONING},
                explicit_model_id=self.model_id
            )
            
            if not self.model:
                raise RuntimeError("No suitable reasoning model found for analysis")
            
            model_name = self._resolved_model_id()
            logger.info(f"Loaded model for analysis: {model_name}")
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    def _order_modes_for_dependencies(self, modes: List[str]) -> List[str]:
        """Order selected modes so dependent analyses can reuse prior results."""
        ordered_modes = list(modes)
        suggested = AnalysisMode.SUGGESTED_ACTIONS.value
        action_items = AnalysisMode.ACTION_ITEMS.value
        if suggested in ordered_modes and action_items in ordered_modes:
            ordered_modes.remove(action_items)
            suggested_index = ordered_modes.index(suggested)
            ordered_modes.insert(suggested_index, action_items)
        return ordered_modes

    async def _analyze_mode(
        self,
        mode: AnalysisMode,
        custom_instructions: Optional[str],
        prior_results: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        completed_modes: Optional[List[str]] = None,
        total_modes: int = 1,
    ) -> Any:
        """
        Execute analysis for a specific mode.
        
        Args:
            mode: Analysis mode to execute
            custom_instructions: Optional custom instructions
            
        Returns:
            Mode-specific analysis result
        """
        try:
            logger.info(f"Running {mode.value} analysis...")

            async def chunk_progress(update: Dict[str, Any]) -> None:
                await self._send_progress(
                    progress_callback,
                    stage=f"analyzing_{mode.value}",
                    stage_progress=float(update.get("stage_progress", 0.0)),
                    completed_modes=completed_modes or [],
                    total_modes=total_modes,
                    message=str(update.get("message") or f"Analyzing {mode.value}..."),
                    current_mode=mode.value,
                )

            executor = MeetingAnalysisExecutor(self.meeting_id, self.prompt_builder)
            try:
                try:
                    result = await executor.analyze_mode(
                        mode=mode,
                        transcript=self.transcript or {},
                        meeting_metadata=self._build_meeting_metadata(),
                        custom_instructions=custom_instructions,
                        prior_results=prior_results or {},
                        model=self.model,
                        progress_callback=chunk_progress,
                    )
                except Exception as first_error:
                    from api.services.model_usage_service import is_model_unreachable_error
                    if self._any_mode_succeeded or not is_model_unreachable_error(first_error):
                        raise
                    fallback_model = await ModelUsageService(get_model_service()).get_designated_local_fallback_model(
                        {ModelCapability.REASONING}
                    )
                    if fallback_model is None:
                        raise
                    logger.warning(
                        f"Reasoning model unreachable ({first_error}); retrying meeting analysis "
                        f"once with local fallback model {fallback_model.model_name}"
                    )
                    self.model = fallback_model
                    self.fallback_model_used = fallback_model.model_name
                    result = await executor.analyze_mode(
                        mode=mode,
                        transcript=self.transcript or {},
                        meeting_metadata=self._build_meeting_metadata(),
                        custom_instructions=custom_instructions,
                        prior_results=prior_results or {},
                        model=self.model,
                        progress_callback=chunk_progress,
                    )
                self._any_mode_succeeded = True
            finally:
                self._safety_omissions.extend(executor.safety_omissions)
            self._structured_output_enforcement[mode.value] = sorted(
                executor.enforcement_modes
            )
            logger.info(f"Completed {mode.value} analysis")
            return result
            
        except Exception as e:
            logger.error(f"Failed to analyze mode {mode.value}: {e}", exc_info=True)
            raise RuntimeError(
                f"Meeting analysis mode {mode.value} failed; refusing to save an incomplete analysis."
            ) from e
    
    def _build_meeting_metadata(self) -> Dict[str, Any]:
        """Build the shared prompt metadata for every analysis mode."""
        return {
            "name": self.metadata.name if self.metadata else None,
            "purpose": self.metadata.purpose if self.metadata else None,
            "participants": self.metadata.participants if self.metadata else [],
            "duration": get_transcript_duration(self.transcript),
            "speaker_count": count_unique_speakers(self.transcript),
            "identity_block": self._identity_block,
            "capability_digest": self._capability_digest,
        }
    
    def _build_action_proposals(self, parsed_data: Any) -> List[MeetingActionProposal]:
        """Compatibility wrapper for focused tests and internal callers."""
        drafts = [SuggestedActionDraft.model_validate(item) for item in parsed_data]
        return build_action_proposals(drafts, meeting_id=self.meeting_id)
    
    @staticmethod
    def _build_mode_failure(mode: AnalysisMode, error: Exception) -> AnalysisModeFailure:
        """Convert nested execution errors into a client-safe durable outcome."""
        current: BaseException | None = error
        while current is not None:
            if isinstance(current, StructuredModelOutputError):
                return AnalysisModeFailure(
                    mode=mode.value,
                    category=current.category,
                    message=str(current),
                    retryable=current.retryable,
                    refusal_category=current.refusal_category,
                    refusal_explanation=current.refusal_explanation,
                )
            current = current.__cause__
        return AnalysisModeFailure(
            mode=mode.value,
            category="internal",
            message=str(error),
            retryable=False,
        )

    def _build_analysis_result(
        self,
        modes: List[str],
        results: Dict[str, Any],
        custom_instructions: Optional[str],
        processing_time: float,
        failed_modes: List[AnalysisModeFailure],
        safety_omissions: Optional[List[AnalysisSafetyOmission]] = None,
    ) -> MeetingAnalysisResult:
        """Build final MeetingAnalysisResult from individual mode results."""
        model_name = self._resolved_model_id()

        # For a merged session analysis the representative metadata name still
        # carries the per-source suffix the client appends (e.g. " - Microphone").
        # Strip it so the results window shows the clean meeting name.
        meeting_name = self.metadata.name if self.metadata else None
        if meeting_name and self.metadata and self.metadata.audio_source:
            suffix = f" - {self.metadata.audio_source}"
            if meeting_name.endswith(suffix):
                meeting_name = meeting_name[: -len(suffix)]
        
        return MeetingAnalysisResult(
            meeting_id=self.meeting_id,
            analyzed_at=datetime.utcnow(),
            model_used=model_name,
            fallback_model_used=self.fallback_model_used,
            requested_modes=modes,
            modes_analyzed=list(results),
            failed_modes=failed_modes,
            safety_omissions=safety_omissions or [],
            custom_instructions=custom_instructions,
            action_items=results.get(AnalysisMode.ACTION_ITEMS.value),
            suggested_actions=results.get(AnalysisMode.SUGGESTED_ACTIONS.value),
            summary=results.get(AnalysisMode.SUMMARY.value),
            decisions=results.get(AnalysisMode.DECISIONS.value),
            questions_answers=results.get(AnalysisMode.QUESTIONS.value),
            sentiment_analysis=results.get(AnalysisMode.SENTIMENT.value),
            custom_analysis=results.get(AnalysisMode.CUSTOM.value),
            structured_output_enforcement=dict(
                self._structured_output_enforcement
            ),
            transcript_duration=get_transcript_duration(self.transcript),
            speaker_count=count_unique_speakers(self.transcript),
            processing_time=processing_time,
            meeting_name=meeting_name,
            meeting_purpose=self.metadata.purpose if self.metadata else None,
            participants=self.metadata.participants if self.metadata else None
        )

    def _resolved_model_id(self) -> str:
        """Return the explicit selection or the loaded model's registry identity."""
        if self.model_id:
            return self.model_id
        return resolve_runtime_model_profile(self.model).model_id
    
    async def _save_analysis(self, analysis: MeetingAnalysisResult) -> None:
        """Save analysis results to disk with timestamped filename."""
        try:
            # Generate timestamp for filename
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f"analysis_{timestamp}.json"
            self.saved_analysis_filename = filename
            analysis_path = self.meeting_dir / filename
            
            # Save analysis file
            analysis_data = analysis.to_dict()
            with open(analysis_path, 'w') as f:
                json.dump(analysis_data, f, indent=2, default=str)
            
            logger.info(f"Saved analysis to {analysis_path}")
            
            # Update metadata with analysis entry
            metadata = MeetingRecorder.load_metadata(self.meeting_id)
            if metadata:
                if metadata.analyses is None:
                    metadata.analyses = []
                
                metadata.analyses.append({
                    "timestamp": analysis.analyzed_at.isoformat() + "Z",
                    "filename": filename,
                    "modes": analysis.modes_analyzed,
                    "model_used": analysis.model_used
                })
                
                # Save updated metadata
                metadata_path = self.meeting_dir / "metadata.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata.to_dict(), f, indent=2)
                
                logger.info(f"Updated metadata with analysis entry: {filename}")
            
        except Exception as e:
            logger.error(f"Failed to save analysis: {e}")
            # Don't raise - analysis was still successful even if save failed
    
    async def _send_progress(
        self,
        callback: Optional[Callable],
        stage: str,
        stage_progress: float,
        completed_modes: List[str],
        total_modes: int,
        message: str,
        current_mode: Optional[str] = None
    ) -> None:
        """Send progress update via callback."""
        if not callback:
            return
        
        # Calculate overall progress
        completed_count = len(completed_modes)
        mode_weight = 1.0 / total_modes if total_modes > 0 else 0.0
        overall_progress = (completed_count * mode_weight) + (stage_progress * mode_weight)
        overall_progress = min(1.0, max(0.0, overall_progress))
        
        progress = AnalysisProgress(
            stage=stage,
            stage_progress=stage_progress,
            overall_progress=overall_progress,
            current_mode=current_mode,
            completed_modes=completed_modes,
            total_modes=total_modes,
            message=message,
            eta_seconds=0.0  # Could implement ETA estimation later
        )
        
        try:
            await callback(progress.to_dict())
        except Exception as e:
            logger.error(f"Failed to send progress update: {e}")

