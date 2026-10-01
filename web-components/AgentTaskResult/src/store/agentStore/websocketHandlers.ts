import type {
  CheckpointData,
  CommandInputMetadata,
  ProviderPermissionApprovalMetadata,
  ResultSeverity,
  StepDetailEntry,
  StructuredFile,
  ThinkingSegment,
  WSEvent,
} from '../../types';
import { parseDelegatedProviderReportCardsForParent } from '../../artifacts/artifactContract';
import { BlockerEventAgentStore } from './blockerEventActions';
import { normalizeCheckpointPayload } from './checkpointNormalization';
import { parseAgentTaskArtifactEvent } from './artifactTimelineReconciliation';
import { deriveResultSeverity } from './timelineDetails';
import { isLiveProgressEvent, isTerminalProgressEvent, parseProgressEvent } from './progressEvent';

export class AgentStore extends BlockerEventAgentStore {
  private markCurrentTurnLive(
    agentTaskId: string,
    event: WSEvent,
    options: { allowTerminalRevival?: boolean } = {}
  ) {
    const eventType = event.event_type as string;
    const isResultStreamingEvent =
      eventType === 'agent_task_streaming' ||
      eventType === 'agent_task_streaming_complete';
    const isStreamingEvent = eventType === 'agent_task_streaming';
    const isActiveExecutionEvent = [
      'agent_task_progress',
      'agent_task_streaming',
      'agent_task_streaming_complete',
      'step_progress_update',
      'dynamic_step_added',
      'dynamic_step_updated',
      'agent_task_step_detail',
      'agent_progress_update',
    ].includes(eventType);

    this.clearPendingStepTimer(agentTaskId);
    this.updateAgent(agentTaskId, a => {
      const priorStatus = a.status;
      const hadStreamedOrPartialText =
        typeof a.result === 'string' && a.result.trim().length > 0;

      // Terminal tasks should not have live noise clear the finished snapshot.
      // Only explicit trusted resume events may move the row back to processing.
      if (priorStatus === 'completed' || priorStatus === 'failed') {
        if (!options.allowTerminalRevival) {
          if (isResultStreamingEvent) {
            a.isStreaming = isStreamingEvent;
          }
          return;
        }
        if (priorStatus === 'failed') {
          a.errorMessage = undefined;
        }
        if (isResultStreamingEvent) {
          a.isStreaming = isStreamingEvent;
        }
      }

      a.status = 'processing';
      a.errorMessage = undefined;
      a.isRetryPending = false;
      if (isActiveExecutionEvent) {
        // A real execution event is authoritative evidence that a previously
        // shown checkpoint is no longer awaiting input. This self-heals a
        // missed checkpoint_resumed event and prevents a stale overlay from
        // forcing the warning bubble or reopening collapsed chrome.
        a.checkpointAvailable = false;
        a.showCheckpointPrompt = false;
        a.currentCheckpoint = undefined;
        a.inlineCheckpoint = undefined;
      }

      // Do not clear the live result while final-synthesis chunks stream; clearing
      // here caused visible flicker when many agent_task_streaming events arrived.
      // Also keep showing accumulated text after streaming_complete while the backend
      // runs finalizer verification (agent_progress_update, etc.); otherwise the UI
      // goes blank until agent_task_result.
      const activePipelineStatus =
        priorStatus === 'routing' ||
        priorStatus === 'capturing' ||
        priorStatus === 'processing' ||
        priorStatus === 'awaitingInput';
      const preserveAccumulatedResult =
        isResultStreamingEvent ||
        (options.allowTerminalRevival && hadStreamedOrPartialText) ||
        (hadStreamedOrPartialText && activePipelineStatus);

      if (!preserveAccumulatedResult) {
        a.result = '';
        a.structuredFiles = [];
      }
      a.isStreaming = isStreamingEvent;
    });
  }

  // --- WebSocket event handling ---

  handleWSEvent(event: WSEvent) {
    const eventType = event.event_type as string;
    const artifactTimelineEntry = eventType === 'agent_task_artifact'
      ? parseAgentTaskArtifactEvent(event)
      : undefined;
    if (eventType === 'agent_task_artifact' && !artifactTimelineEntry) return;

    const sourceAgentTaskId = event.agent_task_id;
    if (typeof sourceAgentTaskId !== 'string' || !sourceAgentTaskId.trim()) return;
    let agentTaskId = sourceAgentTaskId;
    const originalAgentTaskId = agentTaskId;

    const rootTaskId = event.root_task_id as string | undefined;
    const previousTaskId = event.previous_task_id as string | undefined;
    const explicitRootId = rootTaskId;

    if (explicitRootId && explicitRootId !== agentTaskId) {
      const originalId = agentTaskId;
      const isFirstMapping = !this.followUpToParent.has(originalId);
      const rootId = this.resolveCanonicalRootId(explicitRootId);
      if (isFirstMapping) {
        this.beginFollowUpTurn(originalId, rootId);
      }
      agentTaskId = rootId;
      if (!this.agents.has(agentTaskId)) {
        this.registerAgent(agentTaskId);
      }
      this.recordChainIdentity(agentTaskId, rootId, previousTaskId);
      if (isFirstMapping) {
        this.selectedAgentId = rootId;
      }
    } else if (this.followUpToParent.has(agentTaskId)) {
      const mappedTo = this.followUpToParent.get(agentTaskId)!;
      agentTaskId = mappedTo;
      this.recordChainIdentity(agentTaskId, rootTaskId, previousTaskId);
    } else {
      if (!this.agents.has(agentTaskId)) {
        if (eventType === 'agent_task_canceled') {
          console.log(`[AgentStore] Ignoring canceled event for unknown/deleted agent: ${agentTaskId}`);
          return;
        }
        console.log(`[AgentStore] WS new agent created: ${agentTaskId}`);
        this.registerAgent(agentTaskId);
      }
      this.recordChainIdentity(agentTaskId, rootTaskId, previousTaskId);
    }

    if (this.isStaleTerminalForActiveTurn(originalAgentTaskId, agentTaskId, event)) {
      console.warn(`[AgentStore] Ignoring terminal event for stale turn: source=${originalAgentTaskId}, routed=${agentTaskId}, activeFollowUp=${this.activeFollowUpByParent.get(agentTaskId)}`);
      return;
    }

    if (this.isStaleOutcomeUpdateForActiveTurn(originalAgentTaskId, agentTaskId, event)) {
      console.warn(`[AgentStore] Ignoring stale outcome update: source=${originalAgentTaskId}, routed=${agentTaskId}, activeFollowUp=${this.activeFollowUpByParent.get(agentTaskId)}`);
      return;
    }

    const cancellationAllowedEvent = [
      'agent_task_canceled',
      'agent_task_origin',
    ].includes(eventType);
    const cancellationState = this.getAgent(agentTaskId);
    if ((cancellationState?.isCanceled || cancellationState?.isCanceling) && !cancellationAllowedEvent) {
      console.debug(`[AgentStore] Ignoring ${eventType} after cancellation started for ${agentTaskId}`);
      return;
    }

    if (isLiveProgressEvent(event) && eventType !== 'checkpoint_waiting') {
      this.markCurrentTurnLive(agentTaskId, event, {
        allowTerminalRevival: eventType === 'checkpoint_resumed',
      });
    }

    switch (eventType) {
      case 'agent_task_progress':
        this.handleProgress(agentTaskId, event);
        break;
      case 'agent_task_result':
        this.handleResult(agentTaskId, event);
        break;
      case 'agent_task_outcome_update':
        this.handleOutcomeUpdate(agentTaskId, event);
        break;
      case 'agent_task_streaming':
        this.handleStreaming(agentTaskId, event);
        break;
      case 'agent_task_streaming_complete':
        this.handleStreamingComplete(agentTaskId, event);
        break;
      case 'agent_task_canceled':
        this.handleCanceled(agentTaskId, event);
        break;
      case 'step_progress_update':
        this.handleStepProgressUpdate(agentTaskId, event);
        break;
      case 'dynamic_step_added':
        this.handleDynamicStepAdded(agentTaskId, event);
        break;
      case 'dynamic_step_updated':
        this.handleDynamicStepUpdated(agentTaskId, event);
        break;
      case 'agent_task_step_detail':
        this.handleStepDetail(agentTaskId, event);
        break;
      case 'agent_progress_update':
        this.handleAgentProgress(agentTaskId, event);
        break;
      case 'collaborative_checkpoint_request':
        this.handleCheckpointRequest(agentTaskId, originalAgentTaskId, event);
        break;
      case 'checkpoint_waiting': {
        const waitingMessage = event.message as string || 'Waiting for input...';
        this.updateProgressStep(agentTaskId, waitingMessage, true, false);
        this.updateStep(agentTaskId, waitingMessage);
        break;
      }
      case 'checkpoint_resumed':
        this.markCheckpointResumeProcessing(agentTaskId, event.message as string || 'Resumed');
        this.recordVisibleProgressUpdate(agentTaskId, event.message as string || 'Resumed', true, false);
        break;
      case 'session_context_info':
        this.recordVisibleProgressUpdate(agentTaskId, event.message as string || 'Context loaded', true, false);
        break;
      case 'agent_task_blocker_waiting':
        this.handleBlockerWaiting(agentTaskId, event);
        break;
      case 'agent_task_blocker_resolved':
        this.handleBlockerResolved(agentTaskId, event);
        break;
      case 'execution_approval_request':
        this.handleApprovalRequest(agentTaskId, originalAgentTaskId, event);
        break;
      case 'agent_task_origin': {
        const originType = event.origin_type;
        const originId = event.origin_id;
        if (
          typeof originType === 'string' && originType.trim()
          && typeof originId === 'string' && originId.trim()
        ) {
          this.updateAgentOrigin(agentTaskId, originType, originId);
        }
        break;
      }
      case 'delegated_provider_report_cards': {
        const cards = parseDelegatedProviderReportCardsForParent(
          originalAgentTaskId,
          event.delegated_provider_report_cards,
        );
        if (cards) {
          this.setDelegatedProviderReportCards(agentTaskId, cards);
        }
        break;
      }
      case 'agent_task_artifact': {
        this.upsertTimelineEntry(agentTaskId, artifactTimelineEntry!);
        break;
      }
      default:
        break;
    }

    this.clearTerminalFollowUpTurnIfNeeded(originalAgentTaskId, agentTaskId, event);
  }

  private isStaleTerminalForActiveTurn(originalAgentTaskId: string, routedAgentTaskId: string, event: WSEvent): boolean {
    if (!isTerminalProgressEvent(event)) return false;
    const activeFollowUpId = this.activeFollowUpByParent.get(routedAgentTaskId);
    return !!activeFollowUpId && activeFollowUpId !== originalAgentTaskId;
  }

  // A late outcome update (async cloud verification, ~30s post-turn) must not
  // clobber a newer turn's result if the user started a follow-up meanwhile.
  private isStaleOutcomeUpdateForActiveTurn(originalAgentTaskId: string, routedAgentTaskId: string, event: WSEvent): boolean {
    if ((event.event_type as string) !== 'agent_task_outcome_update') return false;
    const activeFollowUpId = this.activeFollowUpByParent.get(routedAgentTaskId);
    return !!activeFollowUpId && activeFollowUpId !== originalAgentTaskId;
  }

  private clearTerminalFollowUpTurnIfNeeded(originalAgentTaskId: string, routedAgentTaskId: string, event: WSEvent) {
    const parentId = this.followUpToParent.get(originalAgentTaskId);
    if (!parentId || parentId !== routedAgentTaskId) return;

    if (isTerminalProgressEvent(event)) {
      this.clearActiveFollowUpTurn(parentId, originalAgentTaskId);
    }
  }

  private handleProgress(agentTaskId: string, event: WSEvent) {
    if (this.isAgentCanceled(agentTaskId)) return;
    const streaming = event.streaming as boolean | undefined;
    if (streaming) {
      const partialResult = event.partial_result as string;
      if (partialResult) {
        this.appendStreamingResult(agentTaskId, partialResult);
      }
      return;
    }

    const parsed = parseProgressEvent(event);
    if (parsed.timelineEntry) this.upsertTimelineEntry(agentTaskId, parsed.timelineEntry);
    this.setCurrentActivityPhase(agentTaskId, parsed.currentPhase);
    const step = parsed.progressStep?.step;
    const status = event.status as string | undefined;
    const details = event.details as string | undefined;
    const transcription = (event.transcription as string | undefined) || (event.details as string | undefined);

    if (transcription && (!step || step === 'Analyzing request')) {
      this.updateAgentTaskText(agentTaskId, transcription);
    }

    if (step) {
      this.recordVisibleProgressUpdate(
        agentTaskId,
        step,
        parsed.progressStep?.isActive ?? (status === 'started' || status === 'in_progress'),
        parsed.progressStep?.isComplete ?? status === 'completed',
      );
    }

    if (status === 'error' || status === 'failed') {
      this.setError(agentTaskId, details || 'An error occurred');
    }
  }

  private handleResult(agentTaskId: string, event: WSEvent) {
    if (this.isAgentCanceled(agentTaskId)) return;
    const resultPayload = (
      event.result_payload ?? event.payload
    ) as Record<string, unknown> | undefined;
    const result = (event.result as string) || (resultPayload?.result as string) || '';
    const files = Array.isArray(resultPayload?.files)
      ? (resultPayload.files as StructuredFile[]).map(file => ({
          ...file,
          path: file.path || (file as StructuredFile & { full_path?: string }).full_path || '',
        })).filter(file => Boolean(file.path))
      : [];
    const error = event.error as string | undefined;
    const outcome =
      (event.outcome as string | undefined) ||
      (resultPayload?.outcome as string | undefined);
    const resultSeverity =
      (event.result_severity as ResultSeverity | undefined) ||
      deriveResultSeverity(error ? 'failed' : 'completed', outcome);
    const rootTaskId =
      (event.root_task_id as string) ||
      (resultPayload?.root_task_id as string);

    if (rootTaskId) {
      this.setRootTaskId(agentTaskId, rootTaskId);
    }
    this.recordChainIdentity(agentTaskId, rootTaskId, event.previous_task_id as string | undefined);

    const now = new Date().toISOString();
    const requiresClarification =
      event.requires_clarification === true ||
      event.needs_clarification === true;

    if (requiresClarification) {
      const clarificationPrompt =
        (event.clarification_question as string | undefined)?.trim() ||
        result ||
        error ||
        'Could you clarify your request?';

      const checkpoint: CheckpointData = {
        checkpoint_id: `clarification-${agentTaskId}-${Date.now()}`,
        prompt: clarificationPrompt,
        input_type: 'data',
        metadata: {
          source: 'clarification',
          retry_count: event.retry_count,
        },
      };

      this.updateAgent(agentTaskId, a => {
        a.result = clarificationPrompt;
        a.errorMessage = undefined;
        a.structuredFiles = files;
        a.timestamp = now;
      });

      this.showCheckpoint(agentTaskId, checkpoint);
      return;
    }

    if (error && result) {
      this.updateAgent(agentTaskId, a => {
        a.errorMessage = error;
        a.result = result;
        a.structuredFiles = files;
        a.status = 'failed';
        a.outcome = outcome;
        a.resultSeverity = resultSeverity;
        a.verificationStatus = resultPayload?.verification_status as 'pending' | 'resolved' | undefined;
        a.isStreaming = false;
        a.timestamp = now;
      });
    } else if (error) {
      this.setError(agentTaskId, error);
      this.updateAgent(agentTaskId, a => {
        a.outcome = outcome;
        a.resultSeverity = resultSeverity;
        a.timestamp = now;
      });
    } else {
      this.setResult(agentTaskId, result, files);
      this.updateAgent(agentTaskId, a => {
        a.outcome = outcome || a.outcome;
        a.resultSeverity = resultSeverity;
        a.verificationStatus = resultPayload?.verification_status as 'pending' | 'resolved' | undefined;
        a.timestamp = now;
      });
    }
  }

  private handleOutcomeUpdate(agentTaskId: string, event: WSEvent) {
    if (this.isAgentCanceled(agentTaskId)) return;
    const resultPayload = (
      event.result_payload ?? event.payload
    ) as Record<string, unknown> | undefined;
    const success = event.success as boolean | undefined;
    const outcome =
      (event.outcome as string | undefined) ||
      (resultPayload?.outcome as string | undefined);
    const resultSeverity = deriveResultSeverity(success === false ? 'failed' : 'completed', outcome);
    const result = event.result as string | undefined;
    const outcomeReason = event.outcome_reason as string | undefined;
    const files = Array.isArray(resultPayload?.files)
      ? (resultPayload.files as StructuredFile[]).map(file => ({
          ...file,
          path: file.path || (file as StructuredFile & { full_path?: string }).full_path || '',
        })).filter(file => Boolean(file.path))
      : undefined;

    this.updateAgent(agentTaskId, a => {
      a.outcome = outcome;
      a.resultSeverity = resultSeverity;
      a.verificationStatus = 'resolved';
      if (typeof result === 'string' && result.trim()) a.result = result;
      if (files) a.structuredFiles = files;
      if (success === false) {
        a.status = 'failed';
        a.errorMessage = outcomeReason?.trim()
          || (outcome === 'partial'
            ? 'Some requested work remains incomplete.'
            : 'The request could not be completed.');
      } else if (success === true) {
        a.status = 'completed';
        a.errorMessage = undefined;
      }
    });
  }

  private handleStreaming(agentTaskId: string, event: WSEvent) {
    if (this.isAgentCanceled(agentTaskId)) return;
    const partialResult = event.partial_result as string;
    if (partialResult) {
      this.appendStreamingResult(agentTaskId, partialResult);
    }
  }

  private handleStreamingComplete(agentTaskId: string, event: WSEvent) {
    if (this.isAgentCanceled(agentTaskId)) return;
    const finalResult =
      (event.final_result as string | undefined) ||
      (event.result as string | undefined) ||
      '';
    this.updateAgent(agentTaskId, a => {
      if (finalResult) {
        a.result = finalResult;
      }
      a.isStreaming = false;
      a.timestamp = new Date().toISOString();
    });
  }

  private handleCanceled(agentTaskId: string, event: WSEvent) {
    const message = (event.message as string | undefined) || 'Agent task canceled';
    if (this.isTransientWithoutDurableData(agentTaskId)) {
      this.removeAgent(agentTaskId);
      return;
    }
    this.hideApproval(agentTaskId);
    this.hideCheckpoint(agentTaskId);
    this.updateAgent(agentTaskId, a => {
      a.status = 'failed';
      a.isStreaming = false;
      a.isCanceling = false;
      a.isCanceled = true;
      a.cancellationError = undefined;
      a.currentStep = 'Canceled';
      a.errorMessage = message;
      a.timestamp = new Date().toISOString();
    });
    this.updateProgressStep(agentTaskId, 'Canceled', false, true);
  }

  private handleStepProgressUpdate(agentTaskId: string, event: WSEvent) {
    const status = event.status as string;
    const stepDesc = event.step_description as string;
    if (stepDesc) {
      const isActive = status === 'running' || status === 'started';
      const isComplete = status === 'completed';
      this.recordVisibleProgressUpdate(agentTaskId, stepDesc, isActive, isComplete);
    }
  }

  private handleDynamicStepAdded(agentTaskId: string, event: WSEvent) {
    const parsed = parseProgressEvent(event);
    const dynamicStep = event.step as { id: string; description: string };
    const step = dynamicStep?.description
      ? dynamicStep
      : parsed.progressStep
        ? { id: parsed.progressStep.id || `dynamic-${parsed.progressStep.step}`, description: parsed.progressStep.step }
        : undefined;
    if (parsed.timelineEntry) this.upsertTimelineEntry(agentTaskId, parsed.timelineEntry);
    this.setCurrentActivityPhase(agentTaskId, parsed.currentPhase);
    if (step) {
      this.recordVisibleProgressUpdate(agentTaskId, step.description, true, false);
    }
  }

  private handleDynamicStepUpdated(agentTaskId: string, event: WSEvent) {
    const status = event.status as string;
    const parsed = parseProgressEvent(event);
    if (parsed.timelineEntry) this.upsertTimelineEntry(agentTaskId, parsed.timelineEntry);
    this.setCurrentActivityPhase(agentTaskId, parsed.currentPhase);
    if (parsed.progressStep) {
      this.recordVisibleProgressUpdate(
        agentTaskId,
        parsed.progressStep.step,
        status === 'running' || status === 'started',
        status === 'completed',
      );
    }
    if (status === 'running' || status === 'started') {
      this.updateStatus(agentTaskId, 'processing');
    }
  }

  private handleAgentProgress(agentTaskId: string, event: WSEvent) {
    const parsed = parseProgressEvent(event);
    if (parsed.timelineEntry) this.upsertTimelineEntry(agentTaskId, parsed.timelineEntry);
    this.setCurrentActivityPhase(agentTaskId, parsed.currentPhase);
    const step = parsed.progressStep?.step;
    const status = event.status as string | undefined;
    if (step) {
      const isActive = !status || status === 'started' || status === 'in_progress';
      const isComplete = status === 'completed';

      // Heartbeat messages contain a changing token count (e.g. "Reasoning… (~355 tokens)").
      // Normalize to a stable key so updateProgressStep matches the existing entry
      // instead of creating a duplicate for every heartbeat.
      const heartbeatPrefix = step.match(/^(.+?)\s*\(~\d+ tokens?\)$/);
      const normalizedStep = heartbeatPrefix ? heartbeatPrefix[1].trimEnd() : step;
      const isHeartbeat = !!heartbeatPrefix;

      this.recordVisibleProgressUpdate(agentTaskId, normalizedStep, isActive, isComplete);

      if (!parsed.timelineEntry && !isHeartbeat) {
        const entryType = isComplete ? 'tool_complete' : 'step';
        this.upsertTimelineEntry(agentTaskId, {
          type: entryType, timestamp: new Date().toISOString(), content: step,
        });
      }

    }

    const thinking = event.thinking as string | undefined;
    const thinkingComplete = event.thinking_complete as boolean | undefined;
    const thinkingIteration = event.thinking_iteration as number | undefined;
    if (thinking !== undefined || thinkingComplete !== undefined) {
      this.updateAgent(agentTaskId, a => {
        if (thinking !== undefined) a.thinking = thinking;
        if (thinkingComplete !== undefined) a.thinkingComplete = thinkingComplete;

        if (thinking !== undefined && thinkingIteration !== undefined) {
          const idx = a.thinkingSegments.findIndex(s => s.iteration === thinkingIteration);
          const segment: ThinkingSegment = {
            iteration: thinkingIteration,
            text: thinking,
            isComplete: thinkingComplete ?? false,
          };
          if (idx >= 0) {
            a.thinkingSegments[idx] = segment;
          } else {
            a.thinkingSegments.push(segment);
            a.executionTimeline.push({
              type: 'thinking', timestamp: new Date().toISOString(),
              content: thinking, iteration: thinkingIteration,
            });
          }
        }
      });
    }
  }

  private handleStepDetail(agentTaskId: string, event: WSEvent) {
    const parsed = parseProgressEvent(event);
    if (parsed.timelineEntry) {
      this.upsertTimelineEntry(agentTaskId, parsed.timelineEntry);
      this.setCurrentActivityPhase(agentTaskId, parsed.currentPhase);
      return;
    }
    const rawEntry = event.entry as Partial<StepDetailEntry> | undefined;
    if (!rawEntry) return;

    const id = rawEntry.id || `${rawEntry.detail_kind || 'detail'}-${Date.now()}`;
    const timestamp = rawEntry.timestamp || new Date().toISOString();
    const summary = rawEntry.summary || rawEntry.content || 'Execution detail';
    const body = rawEntry.body || rawEntry.content || summary;
    const detail: StepDetailEntry = {
      id,
      type: rawEntry.type,
      timestamp,
      content: rawEntry.content || summary,
      step_id: rawEntry.step_id,
      correlation_id: rawEntry.correlation_id || rawEntry.step_id || id,
      detail_kind: rawEntry.detail_kind || rawEntry.type || 'step_note',
      summary,
      body,
      metadata: rawEntry.metadata,
      streaming: rawEntry.streaming,
    };

    this.upsertStepDetail(agentTaskId, detail, event.delta as string | undefined);
  }

  private handleCheckpointRequest(storeAgentTaskId: string, sessionAgentTaskId: string, event: WSEvent) {
    const checkpoint = normalizeCheckpointPayload(sessionAgentTaskId, event);
    if (checkpoint) {
      this.showCheckpoint(storeAgentTaskId, checkpoint);
    }
  }

  private handleApprovalRequest(agentTaskId: string, approvalAgentTaskId: string, event: WSEvent) {
    const approval = {
      approval_id: event.approval_id as string,
      agent_task_id: approvalAgentTaskId,
      command: event.command as string,
      reason: event.reason as string,
      risk_level: event.risk_level as 'low' | 'medium' | 'high' | 'critical',
      generalized_pattern: event.generalized_pattern as string | undefined,
      risk_metadata: event.risk_metadata as Record<string, unknown> | undefined,
      script_content: event.script_content as string | undefined,
      execution_type: event.execution_type as
        | 'shell'
        | 'applescript'
        | 'browser_sensitive_fill'
        | 'provider_permission'
        | 'command_input'
        | undefined,
      browser_metadata: event.browser_metadata as Record<string, unknown> | undefined,
      provider_permission: event.provider_permission as ProviderPermissionApprovalMetadata | undefined,
      command_input: event.command_input as CommandInputMetadata | undefined,
      revision: event.revision as number | undefined,
    };
    const waitingMessage = approval.execution_type === 'command_input'
      ? 'Waiting for your input'
      : 'Waiting for your approval';
    this.showApproval(agentTaskId, approval);
    this.updateProgressStep(agentTaskId, waitingMessage, true, false);
    this.updateStep(agentTaskId, waitingMessage);
  }
}
