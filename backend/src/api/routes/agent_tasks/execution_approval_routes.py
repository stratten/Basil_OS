"""Command execution approval and whitelist routes for agent tasks."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.core.models.preferences import ExecutionApprovalMode
from api.core.preferences.preferences_io import load_preferences, save_preferences
from api.core.security.backend_request_guard import require_host_credential
from api.core.security.execution_approval_risk import (
    added_whitelist_pattern_risk,
    approval_settings_change_risk,
    require_risk_confirmation,
    updated_whitelist_pattern_risk,
)
from api.services.agent_processing.tools.safety import ExecutionApprovalService

from .execution_models import (
    AddWhitelistRequest,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalSettingsResponse,
    DeleteWhitelistResponse,
    ExecutionApprovalRequest,
    ExecutionApprovalResponse,
    UpdateApprovalSettingsRequest,
    WhitelistPattern,
    WhitelistResponse,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.execution_approvals.repository import (
    ExecutionApprovalConflictError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

async def get_approval_service(request: Request) -> ExecutionApprovalService:
    """Get command approval service from app state."""
    service = getattr(request.app.state, "execution_approval_service", None)
    if service is None:
        # Create singleton instance
        service = ExecutionApprovalService()
        request.app.state.execution_approval_service = service
    return service


@router.post("/approval/evaluate", response_model=ExecutionApprovalResponse)
async def evaluate_execution_approval(
    request: ExecutionApprovalRequest,
    approval_service: ExecutionApprovalService = Depends(get_approval_service)
):
    """
    Evaluate whether a command needs approval before execution.
    
    Args:
        request: Command approval request
        
    Returns:
        Approval decision with risk assessment
    """
    try:
        decision = await approval_service.evaluate_command(
            request.command,
            context=request.context
        )
        
        return ExecutionApprovalResponse(
            needs_approval=decision.needs_approval,
            reason=decision.reason,
            risk_level=decision.risk_level,
            is_blocked=decision.is_blocked,
            block_reason=decision.block_reason,
            matched_pattern_id=decision.matched_pattern.id if decision.matched_pattern else None
        )
        
    except Exception as e:
        logger.error(f"Error evaluating command approval: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to evaluate approval: {str(e)}")


@router.post("/approval/decide", response_model=ApprovalDecisionResponse)
async def process_approval_decision(
    request: ApprovalDecisionRequest,
    approval_service: ExecutionApprovalService = Depends(get_approval_service)
):
    """
    Process user's approval decision for a command.
    
    This endpoint is called by the frontend when the user approves/denies a command.
    It resolves the pending approval Future and optionally adds to whitelist.
    
    Args:
        request: Approval decision with approval_id, approved flag, and optional remember settings
        
    Returns:
        Result of processing the decision
    """
    try:
        pattern_id = None

        await approval_service.handle_approval_response(
            approval_id=request.approval_id,
            approved=request.approved,
            remember=request.remember_choice,
            pattern_type=request.pattern_type,
            agent_task_id=request.agent_task_id,
            expected_revision=request.expected_revision,
        )
        
        logger.info(f"Approval decision processed: approval_id={request.approval_id}, approved={request.approved}")

        from api.dependencies import get_sqlite_knowledge_service

        # The whitelist must record the command the backend asked about, not whatever the client echoes back.
        durable_approval = await get_sqlite_knowledge_service().execution_approval_repository.get_approval(
            request.approval_id
        )

        if request.approved and request.remember_choice and durable_approval is not None:
            approved_command = str(durable_approval["command"])
            pattern = await approval_service.add_to_whitelist(
                command=approved_command,
                pattern_type=request.pattern_type,
                description=request.description or f"User-approved: {approved_command}",
                risk_level='low',  # User-approved commands are considered low risk
                record_initial_use=True,
            )
            pattern_id = pattern.id
            message = "Command approved and added to whitelist"
        elif request.approved:
            message = "Command approved for this execution"
        else:
            message = "Command denied"
        
        return ApprovalDecisionResponse(
            success=True,
            message=message,
            pattern_id=pattern_id
        )
        
    except ExecutionApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        logger.error(f"Error processing approval decision: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process decision: {str(e)}")


@router.get("/approval/settings", response_model=ApprovalSettingsResponse)
async def get_approval_settings():
    """
    Get current command approval settings.
    
    Returns:
        Current approval configuration
    """
    try:
        logger.info("📋 [APPROVAL_SETTINGS] Loading preferences...")
        preferences = load_preferences()
        logger.info(f"📋 [APPROVAL_SETTINGS] Preferences loaded. Has tool_execution: {hasattr(preferences, 'tool_execution')}")
        
        settings = preferences.tool_execution
        logger.info(f"📋 [APPROVAL_SETTINGS] Command execution settings: approval_mode={settings.approval_mode}, type={type(settings.approval_mode)}")
        logger.info(f"📋 [APPROVAL_SETTINGS] Settings fields: show_full={settings.show_full_command_in_prompt}, remember={settings.remember_choice_option}, auto_approve_read_only={settings.auto_approve_read_only}, block_dangerous={settings.block_dangerous_patterns}")
        logger.info(f"📋 [APPROVAL_SETTINGS] Whitelisted commands count: {len(settings.whitelisted_commands)}")
        
        response = ApprovalSettingsResponse(
            approval_mode=settings.approval_mode.value,
            show_full_command_in_prompt=settings.show_full_command_in_prompt,
            remember_choice_option=settings.remember_choice_option,
            auto_approve_read_only=settings.auto_approve_read_only,
            block_dangerous_patterns=settings.block_dangerous_patterns,
            whitelisted_count=len(settings.whitelisted_commands),
            safe_execution_mode=settings.safe_execution_mode,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            timeout_behavior=settings.timeout_behavior.value,
        )
        
        logger.info(f"📋 [APPROVAL_SETTINGS] Response created successfully: {response.model_dump()}")
        logger.info("📋 [APPROVAL_SETTINGS] Finished processing request")
        return response
        
    except Exception as e:
        logger.error(f"❌ [APPROVAL_SETTINGS] Error getting approval settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")


@router.post("/approval/settings", response_model=ApprovalSettingsResponse, dependencies=[Depends(require_host_credential)])
async def update_approval_settings(
    request: UpdateApprovalSettingsRequest,
    http_request: Request,
):
    """
    Update command approval settings.
    
    Args:
        request: Settings to update
        
    Returns:
        Updated settings
    """
    try:
        preferences = load_preferences()
        settings = preferences.tool_execution
        require_risk_confirmation(
            http_request,
            approval_settings_change_risk(
                requested_approval_mode=request.approval_mode,
                requested_block_dangerous_patterns=request.block_dangerous_patterns,
                requested_safe_execution_mode=request.safe_execution_mode,
                current_approval_mode=settings.approval_mode.value,
                current_block_dangerous_patterns=settings.block_dangerous_patterns,
                current_safe_execution_mode=settings.safe_execution_mode,
            ),
        )
        
        # Update provided fields
        if request.approval_mode is not None:
            settings.approval_mode = ExecutionApprovalMode(request.approval_mode)
        if request.show_full_command_in_prompt is not None:
            settings.show_full_command_in_prompt = request.show_full_command_in_prompt
        if request.remember_choice_option is not None:
            settings.remember_choice_option = request.remember_choice_option
        if request.auto_approve_read_only is not None:
            settings.auto_approve_read_only = request.auto_approve_read_only
        if request.block_dangerous_patterns is not None:
            settings.block_dangerous_patterns = request.block_dangerous_patterns
        if request.safe_execution_mode is not None:
            settings.safe_execution_mode = request.safe_execution_mode
        if request.approval_timeout_seconds is not None:
            settings.approval_timeout_seconds = request.approval_timeout_seconds
        if request.timeout_behavior is not None:
            from api.core.models.preferences import ApprovalTimeoutBehavior
            settings.timeout_behavior = ApprovalTimeoutBehavior(request.timeout_behavior)
        
        # Save preferences
        save_preferences(preferences)
        
        return ApprovalSettingsResponse(
            approval_mode=settings.approval_mode.value,
            show_full_command_in_prompt=settings.show_full_command_in_prompt,
            remember_choice_option=settings.remember_choice_option,
            auto_approve_read_only=settings.auto_approve_read_only,
            block_dangerous_patterns=settings.block_dangerous_patterns,
            whitelisted_count=len(settings.whitelisted_commands),
            safe_execution_mode=settings.safe_execution_mode,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            timeout_behavior=settings.timeout_behavior.value,
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid approval mode: {str(e)}")
    except Exception as e:
        logger.error(f"Error updating approval settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


@router.get("/whitelist", response_model=WhitelistResponse)
async def get_whitelist_patterns():
    """
    Get all whitelisted command patterns.
    
    Returns:
        List of all whitelist patterns
    """
    try:
        logger.info("📝 [WHITELIST] Loading whitelist patterns...")
        preferences = load_preferences()
        patterns = preferences.tool_execution.whitelisted_commands
        logger.info(f"📝 [WHITELIST] Found {len(patterns)} whitelisted patterns")
        
        whitelist_patterns = [
            WhitelistPattern(
                id=p.id,
                pattern=p.pattern,
                pattern_type=p.pattern_type,
                description=p.description,
                added_date=p.added_date,
                last_used=p.last_used,
                use_count=p.use_count,
                risk_level=p.risk_level
            )
            for p in patterns
        ]
        
        logger.info(f"📝 [WHITELIST] Successfully serialized {len(whitelist_patterns)} patterns")
        response = WhitelistResponse(
            patterns=whitelist_patterns,
            total_count=len(whitelist_patterns)
        )
        logger.info(f"📝 [WHITELIST] Response ready with total_count={response.total_count}")
        logger.info("📝 [WHITELIST] Finished processing request")
        return response
        
    except Exception as e:
        logger.error(f"❌ [WHITELIST] Error getting whitelist: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get whitelist: {str(e)}")


@router.post("/whitelist", response_model=WhitelistPattern, dependencies=[Depends(require_host_credential)])
async def add_whitelist_pattern(
    request: AddWhitelistRequest,
    http_request: Request,
    approval_service: ExecutionApprovalService = Depends(get_approval_service)
):
    """
    Add a new pattern to the whitelist.
    
    Args:
        request: Pattern to add
        
    Returns:
        The created whitelist pattern
    """
    try:
        valid_pattern_types = {'exact', 'prefix', 'regex'}
        if request.pattern_type not in valid_pattern_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pattern type. Must be one of: {', '.join(valid_pattern_types)}"
            )
        
        valid_risk_levels = {'low', 'medium', 'high'}
        if request.risk_level not in valid_risk_levels:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid risk level. Must be one of: {', '.join(valid_risk_levels)}"
            )
        
        require_risk_confirmation(http_request, added_whitelist_pattern_risk(request.pattern, request.pattern_type))
        pattern = await approval_service.add_to_whitelist(
            command=request.pattern,
            pattern_type=request.pattern_type,
            description=request.description,
            risk_level=request.risk_level
        )
        
        return WhitelistPattern(
            id=pattern.id,
            pattern=pattern.pattern,
            pattern_type=pattern.pattern_type,
            description=pattern.description,
            added_date=pattern.added_date,
            last_used=pattern.last_used,
            use_count=pattern.use_count,
            risk_level=pattern.risk_level
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding whitelist pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add pattern: {str(e)}")


@router.put("/whitelist/{pattern_id}", response_model=WhitelistPattern, dependencies=[Depends(require_host_credential)])
async def update_whitelist_pattern(
    pattern_id: str,
    request: AddWhitelistRequest,
    http_request: Request,
    approval_service: ExecutionApprovalService = Depends(get_approval_service)
):
    """
    Update an existing whitelist pattern.
    
    Args:
        pattern_id: ID of the pattern to update
        request: Updated pattern data
        
    Returns:
        The updated whitelist pattern
    """
    try:
        logger.info(f"📝 [WHITELIST] Updating pattern {pattern_id}")
        
        valid_pattern_types = {'exact', 'prefix', 'regex'}
        if request.pattern_type not in valid_pattern_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pattern type. Must be one of: {', '.join(valid_pattern_types)}"
            )
        
        require_risk_confirmation(http_request, updated_whitelist_pattern_risk(request.pattern, request.pattern_type))
        pattern = await approval_service.update_whitelist_pattern(
            pattern_id=pattern_id,
            command=request.pattern,
            pattern_type=request.pattern_type,
            description=request.description
        )
        
        if not pattern:
            raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")
        
        logger.info(f"✅ [WHITELIST] Updated pattern {pattern_id}")
        
        return WhitelistPattern(
            id=pattern.id,
            pattern=pattern.pattern,
            pattern_type=pattern.pattern_type,
            description=pattern.description,
            added_date=pattern.added_date,
            last_used=pattern.last_used,
            use_count=pattern.use_count,
            risk_level=pattern.risk_level
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [WHITELIST] Error updating pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update pattern: {str(e)}")


@router.delete("/whitelist/{pattern_id}", response_model=DeleteWhitelistResponse)
async def remove_whitelist_pattern(
    pattern_id: str,
    approval_service: ExecutionApprovalService = Depends(get_approval_service)
) -> DeleteWhitelistResponse:
    """
    Remove a pattern from the whitelist.
    
    Args:
        pattern_id: ID of the pattern to remove
        
    Returns:
        DeleteWhitelistResponse: Success status and message
    """
    try:
        success = await approval_service.remove_from_whitelist(pattern_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")
        
        return DeleteWhitelistResponse(success=True, message="Pattern removed from whitelist")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing whitelist pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to remove pattern: {str(e)}")
