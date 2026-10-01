import type { AgentStatus, AgentTaskDetail, CheckpointData } from '../types';
import { normalizePersistedThinkingSegments } from '../types';
import { parseAgentTaskPresentationSummaryForTask } from '../artifacts/artifactContract';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { normalizeCheckpointData } from '../store/agentStore/checkpointNormalization';

export function backendStatusToAgentStatus(status: string): AgentStatus | null {
  switch (status) {
    case 'routing':
    case 'processing':
    case 'capturing':
    case 'completed':
    case 'failed':
      return status;
    case 'awaiting_user_input':
    case 'needs_clarification':
      return 'awaitingInput';
    default:
      return null;
  }
}

export function isInFlightAgentStatus(status: string | undefined): boolean {
  return status === 'capturing' || status === 'routing' || status === 'processing';
}

const pendingHydrationRetries = new Set<string>();
const hydrationRequestTokens = new Map<string, number>();

export type HydrationOutcome = 'hydrated' | 'retrying' | 'unavailable' | 'superseded';

function scheduleHydrationRetry(agentTaskId: string): void {
  if (pendingHydrationRetries.has(agentTaskId)) return;
  pendingHydrationRetries.add(agentTaskId);
  window.setTimeout(() => {
    pendingHydrationRetries.delete(agentTaskId);
    void hydrateAgentFromBackend(agentTaskId);
  }, 1500);
}

async function restoreAwaitingCheckpoint(
  storeAgentTaskId: string,
  sessionAgentTaskId: string,
  detail: Pick<AgentTaskDetail, 'status' | 'result_message' | 'checkpoint_data'>,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  if (!isCurrent()) return;
  if (detail.status !== 'awaiting_user_input' && detail.status !== 'needs_clarification') return;

  const currentAgent = agentStore.getAgent(storeAgentTaskId);
  if (!currentAgent || currentAgent.status === 'completed' || currentAgent.status === 'failed' || currentAgent.currentCheckpoint) return;

  const checkpoint = normalizeCheckpointData(sessionAgentTaskId, detail.checkpoint_data);
  if (checkpoint) {
    agentStore.showCheckpoint(storeAgentTaskId, checkpoint);
    return;
  }

  try {
    const checkpointStatus = await api.getCheckpointStatus(sessionAgentTaskId);
    if (!isCurrent()) return;
    const latestAgent = agentStore.getAgent(storeAgentTaskId);
    if (!latestAgent || latestAgent.status === 'completed' || latestAgent.status === 'failed' || latestAgent.currentCheckpoint) return;

    if (checkpointStatus.can_resume) {
      const fallbackCheckpoint: CheckpointData = {
        checkpoint_id: `recovered-${sessionAgentTaskId}`,
        session_agent_task_id: sessionAgentTaskId,
        prompt: detail.result_message?.trim() || 'Basil is waiting for your input. Reply to continue this task.',
        input_type: 'data',
        metadata: { source: 'checkpoint_recovery' },
      };
      agentStore.showCheckpoint(storeAgentTaskId, fallbackCheckpoint);
      return;
    }

    agentStore.setError(storeAgentTaskId, 'The saved input request is no longer resumable. Retry the task to start a new run.');
    agentStore.updateStatus(storeAgentTaskId, 'failed');
  } catch (error) {
    console.warn('[AgentTaskResult] Failed to recover awaiting checkpoint', { storeAgentTaskId, error });
  }
}

async function restorePendingExecutionApproval(
  storeAgentTaskId: string,
  sessionAgentTaskId: string,
  isCurrent: () => boolean = () => true,
): Promise<boolean> {
  if (!isCurrent()) return false;
  const currentAgent = agentStore.getAgent(storeAgentTaskId);
  if (!currentAgent || currentAgent.status === 'completed' || currentAgent.status === 'failed') {
    return false;
  }

  try {
    const { approvals, orphaned_approval_ids: orphanedApprovalIds } = await api.getPendingExecutionApprovals(sessionAgentTaskId);
    if (!isCurrent()) return false;
    const latestAgent = agentStore.getAgent(storeAgentTaskId);
    if (!latestAgent || latestAgent.status === 'completed' || latestAgent.status === 'failed') {
      return false;
    }
    if (orphanedApprovalIds.length > 0) {
      await api.recoverOrphanedExecutionApprovals(sessionAgentTaskId, orphanedApprovalIds);
      if (!isCurrent()) return false;
      if (approvals.length === 0) {
        agentStore.setError(
          storeAgentTaskId,
          'Basil restarted while waiting for command approval. Retry the task to reassess the command safely.',
        );
        return false;
      }
    }
    for (const approval of approvals) {
      agentStore.showApproval(storeAgentTaskId, {
        approval_id: approval.approval_id,
        agent_task_id: approval.agent_task_id,
        command: approval.command,
        reason: approval.reason,
        risk_level: approval.risk_level,
        generalized_pattern: approval.generalized_pattern,
        risk_metadata: approval.risk_metadata ?? undefined,
        script_content: approval.script_content ?? undefined,
        execution_type: approval.execution_type,
        revision: approval.revision,
      });
    }
    const restoredCommandInputs = await restorePendingCommandInputs(storeAgentTaskId, sessionAgentTaskId, isCurrent);
    if (!isCurrent()) return false;
    if (approvals.length > 0) {
      agentStore.updateProgressStep(storeAgentTaskId, 'Waiting for your approval', true, false);
      agentStore.updateStep(storeAgentTaskId, 'Waiting for your approval');
      return true;
    }
    if (restoredCommandInputs > 0) {
      agentStore.updateProgressStep(storeAgentTaskId, 'Waiting for your input', true, false);
      agentStore.updateStep(storeAgentTaskId, 'Waiting for your input');
      return true;
    }
    return false;
  } catch (error) {
    console.warn('[AgentTaskResult] Failed to recover pending execution approval', {
      storeAgentTaskId,
      error,
    });
    return false;
  }
}

async function restorePendingCommandInputs(
  storeAgentTaskId: string,
  sessionAgentTaskId: string,
  isCurrent: () => boolean = () => true,
): Promise<number> {
  try {
    const { requests } = await api.getPendingCommandInputs(sessionAgentTaskId);
    if (!isCurrent()) return 0;
    const latestAgent = agentStore.getAgent(storeAgentTaskId);
    if (!latestAgent || latestAgent.status === 'completed' || latestAgent.status === 'failed') {
      return 0;
    }
    for (const pending of requests) {
      agentStore.showApproval(storeAgentTaskId, {
        approval_id: pending.request_id,
        agent_task_id: pending.agent_task_id,
        command: pending.command,
        reason: `The command is asking for input: ${pending.prompt}`,
        risk_level: pending.secret ? 'medium' : 'low',
        execution_type: 'command_input',
        command_input: pending,
      });
    }
    return requests.length;
  } catch (error) {
    console.warn('[AgentTaskResult] Failed to recover pending command input', {
      storeAgentTaskId,
      error,
    });
    return 0;
  }
}

async function restorePendingProviderInteraction(
  storeAgentTaskId: string,
  sessionAgentTaskId: string,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  if (!isCurrent()) return;
  const currentAgent = agentStore.getAgent(storeAgentTaskId);
  if (!currentAgent || currentAgent.status === 'completed' || currentAgent.status === 'failed' || currentAgent.currentCheckpoint) {
    return;
  }

  try {
    const { interaction } = await api.getPendingProviderInteraction(sessionAgentTaskId);
    if (!isCurrent()) return;
    const latestAgent = agentStore.getAgent(storeAgentTaskId);
    if (!interaction || !latestAgent || latestAgent.status === 'completed' || latestAgent.status === 'failed' || latestAgent.currentCheckpoint) {
      return;
    }
    agentStore.showCheckpoint(storeAgentTaskId, {
      checkpoint_id: interaction.id,
      session_agent_task_id: sessionAgentTaskId,
      prompt: interaction.message,
      input_type: 'provider_form',
      fields: interaction.fields,
      metadata: { source: 'provider_user_input' },
    });
  } catch (error) {
    console.warn('[AgentTaskResult] Failed to recover pending provider interaction', {
      storeAgentTaskId,
      error,
    });
  }
}

// Reconciles the local agentStore entry for ``agentTaskId`` against the
// backend's authoritative state. Used by every code path that "opens"
// an existing agent task without knowing whether it is in-flight, terminal,
// or doesn't exist on the backend at all.
export function hydrateAgentFromBackend(agentTaskId: string): Promise<HydrationOutcome> {
  const requestToken = (hydrationRequestTokens.get(agentTaskId) ?? 0) + 1;
  hydrationRequestTokens.set(agentTaskId, requestToken);
  const isCurrentRequest = () => hydrationRequestTokens.get(agentTaskId) === requestToken;
  const isActiveLocalAgentTask = (agent: ReturnType<typeof agentStore.getAgent>): boolean => {
    if (!agent) return false;
    return isInFlightAgentStatus(agent.status) || agent.status === 'awaitingInput';
  };

  const isWithinPersistenceGrace = (agent: ReturnType<typeof agentStore.getAgent>, graceMs = 30_000): boolean => {
    if (!agent?.timestamp) return false;
    const startedAt = Date.parse(agent.timestamp);
    if (Number.isNaN(startedAt)) return false;
    return Date.now() - startedAt < graceMs;
  };

  return api.getAgentTaskDetail(agentTaskId)
    .then(async detail => {
      if (!isCurrentRequest()) return 'superseded';
      pendingHydrationRetries.delete(agentTaskId);
      agentStore.clearTransientAgent(agentTaskId);
      // When this task has follow-ups, the most recent follow-up is the
      // authoritative "current turn". Reading raw `detail.*` fields here
      // instead would silently clobber an already-correct chain hydration
      // (see hydrateDetachedChain in useHostBridge.ts) with the *root's own*
      // turn data, because the root's own backend record is independently
      // terminal the moment any follow-up exists -- this is what caused a
      // detached multi-run window to snap back to showing run 1 after
      // correctly hydrating run 3: this function can race hydrateDetachedChain
      // via App.tsx's in-flight-status reconciliation effect and resolve later.
      const mostRecentFollowUp = detail.follow_ups?.length
        ? detail.follow_ups[detail.follow_ups.length - 1]
        : null;
      const turn = mostRecentFollowUp ?? detail;
      const isTerminal = turn.status === 'completed' || turn.status === 'failed';
      const isRetryPending = agentStore.getAgent(agentTaskId)?.isRetryPending === true;
      if (isTerminal && isRetryPending) {
        console.debug('[AgentTaskResult] Ignoring stale terminal hydration while retry is pending', {
          agentTaskId,
          backendStatus: turn.status,
        });
        return 'hydrated';
      }
      agentStore.updateAgentTaskTitle(agentTaskId, detail.title);
      agentStore.updateAgentOrigin(agentTaskId, detail.origin_type, detail.origin_id);
      agentStore.updateReasoningFallbackModelUsed(agentTaskId, turn.reasoning_fallback_model_used);
      agentStore.updateOriginalModelId(agentTaskId, turn.model_id);
      agentStore.setCurrentTurnTaskId(agentTaskId, mostRecentFollowUp?.id || detail.id);
      if (isTerminal && agentStore.hasActiveFollowUpTurn(agentTaskId)) {
        console.debug('[AgentTaskResult] Ignoring terminal parent hydration while follow-up is active', {
          agentTaskId,
          activeFollowUpId: agentStore.getActiveFollowUpId(agentTaskId),
          backendStatus: turn.status,
        });
        return 'hydrated';
      }

      const prompt = turn.original_prompt || detail.transcribed_prompt;
      if (prompt) {
        agentStore.updateAgentTaskText(agentTaskId, prompt);

        const agent = agentStore.getAgent(agentTaskId);
        if (agent?.currentStep === 'Transcribing audio') {
          agentStore.completeProgressStep(agentTaskId, 'Transcribing audio');
          agentStore.updateProgressStep(agentTaskId, 'Reading screen context', true, false);
          agentStore.updateStep(agentTaskId, 'Reading screen context');
        }
      }
      agentStore.updateAgentDisplayPromptMarkdown(agentTaskId, turn.display_prompt_markdown);

      const localStatus = backendStatusToAgentStatus(turn.status);
      if (localStatus && localStatus !== 'completed' && localStatus !== 'failed') {
        agentStore.updateStatus(agentTaskId, localStatus);
        const presentationSummary = parseAgentTaskPresentationSummaryForTask(
          agentTaskId,
          turn.agent_task_presentation_summary,
        );
        agentStore.setPresentationSummary(agentTaskId, presentationSummary);
        // A reopened task recovers from durable detail, but an older in-flight detail request must not clobber a live card snapshot.
        const hasLiveCards = (agentStore.getAgent(agentTaskId)?.delegatedProviderReportCards?.length ?? 0) > 0;
        if (!hasLiveCards) {
          agentStore.setDelegatedProviderReportCards(
            agentTaskId,
            presentationSummary?.delegatedProviderReportCards ?? [],
          );
        }
        // Pending approvals/checkpoints/provider interactions are keyed by the
        // actual in-flight backend task id, which is the follow-up's own id
        // once one exists -- not the root's id.
        const sessionAgentTaskId = mostRecentFollowUp?.id ?? agentTaskId;
        if (localStatus === 'awaitingInput') {
          const restoredApproval = await restorePendingExecutionApproval(agentTaskId, sessionAgentTaskId, isCurrentRequest);
          if (!isCurrentRequest()) return 'superseded';
          if (!restoredApproval) {
            await restorePendingProviderInteraction(agentTaskId, sessionAgentTaskId, isCurrentRequest);
            if (!isCurrentRequest()) return 'superseded';
            await restoreAwaitingCheckpoint(agentTaskId, sessionAgentTaskId, {
              status: turn.status,
              result_message: turn.result_message,
              // The chain-list endpoint returns checkpoint_data only for the
              // root, not per follow-up -- fall back to the getCheckpointStatus
              // recovery path below instead of applying the root's stale
              // checkpoint onto an active follow-up turn.
              checkpoint_data: mostRecentFollowUp ? undefined : detail.checkpoint_data,
            }, isCurrentRequest);
            if (!isCurrentRequest()) return 'superseded';
          }
        } else {
          // A shell/execution-approval wait never flips the backend status to
          // awaiting_user_input (that status is reserved for the separate
          // collaborative-checkpoint flow), so an in-flight status here can
          // still have a live, un-actioned execution approval -- check for
          // one before falling back to the provider-interaction poll.
          const restoredApproval = await restorePendingExecutionApproval(agentTaskId, sessionAgentTaskId, isCurrentRequest);
          if (!isCurrentRequest()) return 'superseded';
          if (!restoredApproval) {
            await restorePendingProviderInteraction(agentTaskId, sessionAgentTaskId, isCurrentRequest);
            if (!isCurrentRequest()) return 'superseded';
          }
        }
        if (turn.execution_timeline && turn.execution_timeline.length > 0) {
          agentStore.reconcileDurableArtifactTimeline(agentTaskId, turn.execution_timeline);
        }
        // While the task is live, WebSocket progress is the freshest source.
        return 'hydrated';
      }

      if (isTerminal) {
        const presentationSummary = parseAgentTaskPresentationSummaryForTask(
          agentTaskId,
          turn.agent_task_presentation_summary,
        );
        agentStore.setPresentationSummary(agentTaskId, presentationSummary);
        agentStore.setDelegatedProviderReportCards(
          agentTaskId,
          presentationSummary?.delegatedProviderReportCards ?? [],
        );
        if (turn.result_message || (turn.files?.length ?? 0) > 0) {
          agentStore.setResult(agentTaskId, turn.result_message || '', turn.files || []);
          agentStore.setReferencePaths(agentTaskId, turn.reference_paths || []);
        }
        const finalStatus = turn.status === 'failed' ? 'failed' : 'completed';
        agentStore.updateStatus(agentTaskId, finalStatus);
        if (finalStatus === 'failed') {
          agentStore.setError(agentTaskId, turn.error_message || turn.result_message || 'Agent task failed');
        }
        agentStore.setResultOutcome(agentTaskId, turn.outcome, turn.result_severity);
        agentStore.setThinkingSegments(
          agentTaskId,
          normalizePersistedThinkingSegments(turn.thinking_history),
        );
        if (turn.execution_timeline && turn.execution_timeline.length > 0) {
          agentStore.setExecutionTimeline(agentTaskId, turn.execution_timeline);
        }
      } else if (turn.status === 'canceled') {
        if (turn.execution_timeline && turn.execution_timeline.length > 0) {
          agentStore.setExecutionTimeline(agentTaskId, turn.execution_timeline);
        }
        agentStore.setError(agentTaskId, 'Agent task was canceled.');
        agentStore.updateStatus(agentTaskId, 'failed');
      }
      return 'hydrated';
    })
    .catch((error) => {
      if (!isCurrentRequest()) return 'superseded';
      const agent = agentStore.getAgent(agentTaskId);
      const isActivePendingPersistence =
        isActiveLocalAgentTask(agent) && isWithinPersistenceGrace(agent);
      const hasLiveProgress =
        !!agent?.currentStep ||
        (agent?.progressSteps?.length ?? 0) > 0 ||
        (agent?.executionTimeline?.length ?? 0) > 0 ||
        (agent?.stepDetails?.length ?? 0) > 0;

      if (isActivePendingPersistence) {
        console.debug('[AgentTaskResult] Agent task detail not persisted yet; keeping active agent task alive', agentTaskId, error);
        agentStore.updateStatus(agentTaskId, 'processing');
        scheduleHydrationRetry(agentTaskId);
        return 'retrying';
      }

      if (hasLiveProgress) {
        console.warn('[AgentTaskResult] Ignoring agent-task detail hydration failure for live agent task', agentTaskId, error);
        if (isWithinPersistenceGrace(agent)) {
          scheduleHydrationRetry(agentTaskId);
        }
        return 'retrying';
      }

      if (agentStore.isTransientWithoutDurableData(agentTaskId)) {
        agentStore.removeAgent(agentTaskId);
        return 'unavailable';
      }

      agentStore.setError(agentTaskId, 'Agent task is no longer available.');
      agentStore.updateStatus(agentTaskId, 'failed');
      return 'unavailable';
    });
}

// Self-heals the case where a follow-up child's terminal or checkpoint WS event
// was missed. Polling hydrateAgentFromBackend(rootTaskId) alone cannot resolve
// this: the root's *own* turn already finished earlier in the chain, so its
// backend detail is already terminal, and hydrateAgentFromBackend
// deliberately ignores terminal-root hydration while a follow-up is active
// (see the isTerminal + hasActiveFollowUpTurn branch above) -- it's the
// *child's* status that is stale. All follow-up turn state lives merged
// onto the root's store entry (per agentStore.beginFollowUpTurn), and the
// child's own id has no store entry to hydrate into, so this fetches the
// child's detail directly and, once it has actually finished, applies it
// onto the root entry and clears the active-follow-up marker.
export function hydrateActiveFollowUpChild(rootTaskId: string, childId: string): Promise<void> {
  return api.getAgentTaskDetail(childId)
    .then(async detail => {
      if (agentStore.getActiveFollowUpId(rootTaskId) !== childId) {
        // Another follow-up has since started, or a live WS event already
        // resolved this one -- do not stomp on newer state.
        return;
      }

      const isTerminal = detail.status === 'completed' || detail.status === 'failed';
      if (detail.status === 'awaiting_user_input') {
        agentStore.updateStatus(rootTaskId, 'awaitingInput');
        if (detail.execution_timeline && detail.execution_timeline.length > 0) {
          agentStore.reconcileDurableArtifactTimeline(rootTaskId, detail.execution_timeline);
        }
        const isCurrentChild = () => agentStore.getActiveFollowUpId(rootTaskId) === childId;
        const restoredApproval = await restorePendingExecutionApproval(rootTaskId, childId, isCurrentChild);
        if (!restoredApproval) {
          await restoreAwaitingCheckpoint(rootTaskId, childId, detail, isCurrentChild);
        }
        return;
      }
      if (!isTerminal) {
        if (detail.execution_timeline && detail.execution_timeline.length > 0) {
          agentStore.reconcileDurableArtifactTimeline(rootTaskId, detail.execution_timeline);
        }
        // Mirrors the in-flight branch of hydrateAgentFromBackend: a
        // shell/execution-approval wait never flips status to
        // awaiting_user_input, so this genuinely-in-flight child can still
        // have a live, un-actioned execution approval to resurface.
        await restorePendingExecutionApproval(
          rootTaskId,
          childId,
          () => agentStore.getActiveFollowUpId(rootTaskId) === childId,
        );
        return;
      }

      const presentationSummary = parseAgentTaskPresentationSummaryForTask(
        childId,
        detail.agent_task_presentation_summary,
      );
      agentStore.setPresentationSummary(rootTaskId, presentationSummary);
      agentStore.setDelegatedProviderReportCards(
        rootTaskId,
        presentationSummary?.delegatedProviderReportCards ?? [],
      );
      if (detail.result_message || (detail.files?.length ?? 0) > 0) {
        agentStore.setResult(rootTaskId, detail.result_message || '', detail.files || []);
        agentStore.setReferencePaths(rootTaskId, detail.reference_paths || []);
      }
      const finalStatus = detail.status === 'failed' ? 'failed' : 'completed';
      agentStore.updateStatus(rootTaskId, finalStatus);
      if (finalStatus === 'failed') {
        agentStore.setError(rootTaskId, detail.error_message || detail.result_message || 'Agent task failed');
      }
      agentStore.setResultOutcome(rootTaskId, detail.outcome, detail.result_severity);
      agentStore.setThinkingSegments(
        rootTaskId,
        normalizePersistedThinkingSegments(detail.thinking_history),
      );
      if (detail.execution_timeline && detail.execution_timeline.length > 0) {
        agentStore.setExecutionTimeline(rootTaskId, detail.execution_timeline);
      }
      agentStore.updateOriginalModelId(rootTaskId, detail.model_id);
      agentStore.clearActiveFollowUpTurn(rootTaskId, childId);
    })
    .catch((error) => {
      console.debug('[AgentTaskResult] Failed to self-heal active follow-up child status', { rootTaskId, childId, error });
    });
}

