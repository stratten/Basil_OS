import type {
  AgentTaskHistoryItem,
  CheckpointData,
  ExecutionApprovalRequest,
  ProgressStep,
  ResultSeverity,
  StepDetailEntry,
  StructuredFile,
  ThinkingSegment,
  TimelineEntry,
} from '../../types';
import type { AgentTaskPresentationSummary, DelegatedProviderReportCard } from '../../artifacts/artifactContract';
import { FollowUpAgentStore } from './followUpActions';
import {
  deriveResultSeverity,
  detailsFromTimeline,
  timelineEntryToDetail,
  withSelectedArtifact,
} from './timelineDetails';
import { reconcileDurableArtifactEntries } from './artifactTimelineReconciliation';

export class ProgressTimelineAgentStore extends FollowUpAgentStore {
  markCancelling(agentTaskId: string) {
    this.updateAgent(agentTaskId, a => {
      a.isCancelling = true;
      a.cancellationError = undefined;
      a.currentStep = 'Cancelling...';
    });
    this.updateProgressStep(agentTaskId, 'Cancelling...', true, false);
  }

  markCancellationUnconfirmed(agentTaskId: string, message: string) {
    this.updateAgent(agentTaskId, a => {
      a.isCancelling = false;
      a.cancellationError = message;
      a.currentStep = message;
    });
    this.updateProgressStep(agentTaskId, message, false, false);
  }

  updateStep(agentTaskId: string, step: string) {
    const MIN_DISPLAY_MS_RICH = 2500;
    const MIN_DISPLAY_MS_PLANNING = 500;
    const now = Date.now();
    const lastDisplay = this.stepDisplayTimes.get(agentTaskId) ?? 0;
    const elapsed = now - lastDisplay;

    const isPlanningMsg = (s: string) =>
      s.toLowerCase().includes('agent planning step') || s.toLowerCase().includes('planning step');

    const current = this.agents.get(agentTaskId)?.currentStep ?? '';
    const currentIsPlanning = isPlanningMsg(current);
    const newIsPlanning = isPlanningMsg(step);

    // Non-planning messages override planning messages immediately
    if (currentIsPlanning && !newIsPlanning) {
      this.clearPendingStepTimer(agentTaskId);
      this.applyStep(agentTaskId, step);
      return;
    }

    // Planning messages trying to override a rich message must wait longer
    if (!currentIsPlanning && newIsPlanning) {
      if (elapsed < MIN_DISPLAY_MS_RICH) {
        this.clearPendingStepTimer(agentTaskId);
        const remaining = MIN_DISPLAY_MS_RICH - elapsed;
        const timer = setTimeout(() => {
          this.pendingStepTimers.delete(agentTaskId);
          this.applyStep(agentTaskId, step);
        }, remaining);
        this.pendingStepTimers.set(agentTaskId, timer);
        return;
      }
    }

    const minMs = currentIsPlanning ? MIN_DISPLAY_MS_PLANNING : MIN_DISPLAY_MS_RICH;
    if (elapsed >= minMs) {
      this.clearPendingStepTimer(agentTaskId);
      this.applyStep(agentTaskId, step);
    } else {
      this.clearPendingStepTimer(agentTaskId);
      const remaining = minMs - elapsed;
      const timer = setTimeout(() => {
        this.pendingStepTimers.delete(agentTaskId);
        this.applyStep(agentTaskId, step);
      }, remaining);
      this.pendingStepTimers.set(agentTaskId, timer);
    }
  }

  protected applyStep(agentTaskId: string, step: string) {
    this.stepDisplayTimes.set(agentTaskId, Date.now());
    this.updateAgent(agentTaskId, a => { a.currentStep = step; });
  }

  protected recordVisibleProgressUpdate(agentTaskId: string, step: string, isActive: boolean, isComplete: boolean) {
    if (this.isAgentCancelled(agentTaskId)) return;
    this.updateProgressStep(agentTaskId, step, isActive, isComplete);
    if (isActive || isComplete) {
      this.updateStep(agentTaskId, step);
    }
    if (isActive) {
      this.updateStatus(agentTaskId, 'processing');
    }
  }

  appendStreamingResult(agentTaskId: string, partialResult: string) {
    if (this.isAgentCancelled(agentTaskId)) return;
    this.updateAgent(agentTaskId, a => {
      a.result = partialResult;
      a.isStreaming = true;
      a.status = 'processing';
    });
  }

  setResult(agentTaskId: string, result: string, files: StructuredFile[] = []) {
    if (this.isAgentCancelled(agentTaskId)) return;
    this.updateAgent(agentTaskId, a => {
      a.result = result;
      a.structuredFiles = files;
      a.isStreaming = false;
      a.status = 'completed';
      a.isRetryPending = false;
      a.outcome = 'success';
      a.resultSeverity = 'success';
    });
  }

  setPresentationSummary(agentTaskId: string, presentationSummary: AgentTaskPresentationSummary | undefined) {
    this.updateAgent(agentTaskId, agent => {
      agent.presentationSummary = presentationSummary;
    });
  }

  setDelegatedProviderReportCards(agentTaskId: string, cards: DelegatedProviderReportCard[]) {
    this.updateAgent(agentTaskId, agent => {
      agent.delegatedProviderReportCards = cards;
    });
  }

  setReferencePaths(agentTaskId: string, paths: string[]) {
    this.updateAgent(agentTaskId, a => {
      a.referencePaths = paths;
    });
  }

  setResultOutcome(agentTaskId: string, outcome: string | undefined, resultSeverity: ResultSeverity | undefined) {
    this.updateAgent(agentTaskId, a => {
      a.outcome = outcome;
      a.resultSeverity = resultSeverity || deriveResultSeverity(a.status, outcome);
    });
  }

  setError(agentTaskId: string, error: string) {
    if (this.isAgentCancelled(agentTaskId)) return;
    this.updateAgent(agentTaskId, a => {
      a.errorMessage = error;
      a.status = 'failed';
      a.resultSeverity = 'error';
      a.isStreaming = false;
      a.isRetryPending = false;
    });
  }

  resetForRetry(agentTaskId: string) {
    const agent = this.agents.get(agentTaskId);
    if (!agent) return;
    agent.errorMessage = undefined;
    agent.status = 'processing';
    agent.isRetryPending = true;
    agent.result = '';
    agent.presentationSummary = undefined;
    agent.delegatedProviderReportCards = [];
    agent.isStreaming = false;
    agent.isCancelling = false;
    agent.isCancelled = false;
    agent.checkpointAvailable = false;
    agent.showCheckpointPrompt = false;
    agent.currentCheckpoint = undefined;
    agent.inlineCheckpoint = undefined;
    agent.showApprovalPrompt = false;
    agent.approvalRequests = [];
    agent.rememberApprovalChoice = false;
    agent.progressSteps = [];
    agent.executionTimeline = [];
    agent.stepDetails = [];
    agent.currentStep = undefined;
    agent.thinkingSegments = [];
    agent.thinking = undefined;
    agent.thinkingComplete = undefined;
    this.emit();
  }

  setThinkingSegments(agentTaskId: string, segments: ThinkingSegment[]) {
    this.updateAgent(agentTaskId, a => {
      a.thinkingSegments = segments;
    });
  }

  setProgressSteps(agentTaskId: string, steps: ProgressStep[]) {
    this.updateAgent(agentTaskId, a => {
      a.progressSteps = steps;
    });
  }

  addProgressStep(agentTaskId: string, step: ProgressStep) {
    this.updateAgent(agentTaskId, a => {
      const existing = a.progressSteps.findIndex(s => s.step === step.step);
      if (existing >= 0) {
        a.progressSteps[existing] = step;
      } else {
        a.progressSteps.push(step);
      }
    });
  }

  updateProgressStep(agentTaskId: string, stepText: string, isActive: boolean, isComplete: boolean) {
    this.updateAgent(agentTaskId, a => {
      if (isActive) {
        for (const s of a.progressSteps) {
          if (s.isActive) {
            s.isActive = false;
            s.isComplete = true;
          }
        }
      }
      const existing = a.progressSteps.findIndex(s => s.step === stepText);
      if (existing >= 0) {
        a.progressSteps[existing] = { ...a.progressSteps[existing], isActive, isComplete };
      } else {
        a.progressSteps.push({ step: stepText, isActive, isComplete });
      }
    });
  }

  completeProgressStep(agentTaskId: string, stepText: string) {
    this.updateProgressStep(agentTaskId, stepText, false, true);
  }

  clearProgressSteps(agentTaskId: string) {
    this.updateAgent(agentTaskId, a => {
      a.progressSteps = [];
      a.currentStep = '';
      a.executionTimeline = [];
      a.stepDetails = [];
      a.thinkingSegments = [];
      a.isStreaming = false;
    });
  }

  addTimelineEntry(agentTaskId: string, entry: TimelineEntry) {
    this.upsertTimelineEntry(agentTaskId, entry);
  }

  upsertTimelineEntry(agentTaskId: string, entry: TimelineEntry) {
    this.updateAgent(agentTaskId, a => {
      const { artifact: _incomingArtifact, ...rawEntry } = entry;
      const existingIndex = rawEntry.id
        ? a.executionTimeline.findIndex(existing => existing.id === rawEntry.id)
        : -1;
      let timelineEntry: TimelineEntry;
      if (existingIndex >= 0) {
        const { artifact: _existingArtifact, ...existingEntry } = a.executionTimeline[existingIndex];
        timelineEntry = rawEntry.type === 'artifact' && rawEntry.metadata?.event_type === 'agent_task_artifact'
          ? rawEntry
          : {
              ...existingEntry,
              ...rawEntry,
              metadata: {
                ...(existingEntry.metadata || {}),
                ...(rawEntry.metadata || {}),
              },
            };
        a.executionTimeline[existingIndex] = timelineEntry;
      } else {
        timelineEntry = rawEntry;
        a.executionTimeline.push(timelineEntry);
      }
      const detail = timelineEntryToDetail(timelineEntry);
      const detailIndex = detail ? a.stepDetails.findIndex(existing => existing.id === detail.id) : -1;
      if (detail && detailIndex >= 0) {
        a.stepDetails[detailIndex] = withSelectedArtifact({
          ...a.stepDetails[detailIndex],
          ...detail,
          metadata: detail.metadata,
        });
      } else if (detail) {
        a.stepDetails.push(detail);
      }
      const phase = timelineEntry.metadata?.progress_phase;
      if (typeof phase === 'string' && phase.trim()) a.currentActivityPhase = phase;
    });
  }

  reconcileDurableArtifactTimeline(agentTaskId: string, timeline: TimelineEntry[]) {
    this.updateAgent(agentTaskId, agent => {
      const reconciled = reconcileDurableArtifactEntries(
        agent.executionTimeline,
        timeline,
      );
      if (reconciled === agent.executionTimeline) return;
      agent.executionTimeline = reconciled;
      agent.stepDetails = detailsFromTimeline(reconciled);
    });
  }

  setExecutionTimeline(agentTaskId: string, timeline: TimelineEntry[]) {
    this.updateAgent(agentTaskId, a => {
      a.executionTimeline = timeline;
      a.stepDetails = detailsFromTimeline(timeline);
      const currentPhase = [...timeline].reverse()
        .map(entry => entry.metadata?.progress_phase)
        .find((phase): phase is string => typeof phase === 'string' && phase.trim().length > 0);
      a.currentActivityPhase = currentPhase;

      const hydratedProgress = timeline
        .map(entry => {
          const metadata = entry.metadata || {};
          const step = metadata.progress_step as string | undefined;
          const status = metadata.status as string | undefined;
          if (!step || !status) return null;
          return {
            step,
            isActive: status === 'started' || status === 'in_progress',
            isComplete: status === 'completed',
          };
        })
        .filter((step): step is ProgressStep => step !== null);

      if (hydratedProgress.length > 0) {
        a.progressSteps = [];
        for (const progress of hydratedProgress) {
          if (progress.isActive) {
            for (const existing of a.progressSteps) {
              if (existing.isActive) {
                existing.isActive = false;
                existing.isComplete = true;
              }
            }
          }

          const existingIndex = a.progressSteps.findIndex(existing => existing.step === progress.step);
          if (existingIndex >= 0) {
            a.progressSteps[existingIndex] = {
              ...a.progressSteps[existingIndex],
              ...progress,
            };
          } else {
            a.progressSteps.push(progress);
          }
        }

        const latestActive = [...hydratedProgress].reverse().find(progress => progress.isActive);
        const latestProgress = latestActive || hydratedProgress[hydratedProgress.length - 1];
        a.currentStep = latestProgress.step;
      }
    });
  }

  setCurrentActivityPhase(agentTaskId: string, phase: string | undefined) {
    if (!phase?.trim()) return;
    this.updateAgent(agentTaskId, a => {
      a.currentActivityPhase = phase;
    });
  }

  upsertStepDetail(agentTaskId: string, detail: StepDetailEntry, delta?: string) {
    detail = withSelectedArtifact(detail);
    this.updateAgent(agentTaskId, a => {
      const isToolCompletion = detail.type === 'tool_complete' || detail.detail_kind === 'tool_result';
      const pairedDetailIndex = isToolCompletion && detail.step_id
        ? a.stepDetails.findIndex(d =>
          d.step_id === detail.step_id &&
          (d.type === 'tool_start' || d.detail_kind === 'tool_input')
        )
        : -1;
      const existing = pairedDetailIndex >= 0
        ? pairedDetailIndex
        : a.stepDetails.findIndex(d => d.id === detail.id);
      const resolvedDetailId = existing >= 0 ? a.stepDetails[existing].id : detail.id;

      if (existing >= 0) {
        const previous = a.stepDetails[existing];
        const mergedBody = delta
          ? `${previous.body || ''}${delta}`
          : isToolCompletion && previous.body && detail.body && previous.body !== detail.body
            ? `${previous.body}\n\nResult:\n${detail.body}`
            : (detail.body || previous.body);
        a.stepDetails[existing] = withSelectedArtifact({
          ...previous,
          ...detail,
          id: resolvedDetailId,
          body: mergedBody,
          metadata: {
            ...(previous.metadata || {}),
            ...(detail.metadata || {}),
            ...(isToolCompletion ? { status: 'completed' } : {}),
          },
        });
      } else {
        a.stepDetails.push(detail);
      }

      const { artifact: _selectedArtifact, ...timelineDetail } = existing >= 0
        ? a.stepDetails[existing]
        : detail;
      const timelineEntry: TimelineEntry = {
        ...timelineDetail,
        type: detail.type || 'step',
        timestamp: detail.timestamp,
        content: detail.content || detail.summary,
      };
      const timelineIndex = isToolCompletion && detail.step_id
        ? a.executionTimeline.findIndex(e =>
          e.step_id === detail.step_id &&
          (e.type === 'tool_start' || e.detail_kind === 'tool_input')
        )
        : a.executionTimeline.findIndex(e => e.id === detail.id);
      if (timelineIndex >= 0) {
        a.executionTimeline[timelineIndex] = {
          ...a.executionTimeline[timelineIndex],
          ...timelineEntry,
          id: a.executionTimeline[timelineIndex].id || resolvedDetailId,
          type: timelineEntry.type,
          metadata: {
            ...(a.executionTimeline[timelineIndex].metadata || {}),
            ...(timelineEntry.metadata || {}),
            ...(isToolCompletion ? { status: 'completed' } : {}),
          },
        };
      } else {
        a.executionTimeline.push(timelineEntry);
      }
    });
  }

  showApproval(agentTaskId: string, request: ExecutionApprovalRequest) {
    this.updateAgent(agentTaskId, a => {
      a.seenApprovalIds ??= [];
      const isSeen = a.seenApprovalIds.includes(request.approval_id);
      if ((a.status === 'completed' || a.status === 'failed') && isSeen) return;
      const existingIndex = a.approvalRequests.findIndex(
        approval => approval.approval_id === request.approval_id,
      );
      if (existingIndex >= 0) {
        a.approvalRequests[existingIndex] = request;
      } else {
        a.approvalRequests.push(request);
      }
      if (!isSeen) {
        a.seenApprovalIds.push(request.approval_id);
      }
      a.showApprovalPrompt = true;
      a.status = 'awaitingInput';
    });
  }

  hideApproval(agentTaskId: string) {
    this.updateAgent(agentTaskId, a => {
      a.showApprovalPrompt = false;
      a.approvalRequests = [];
    });
  }

  removeApproval(agentTaskId: string, approvalId: string) {
    this.updateAgent(agentTaskId, a => {
      a.approvalRequests = a.approvalRequests.filter(
        approval => approval.approval_id !== approvalId,
      );
      a.showApprovalPrompt = a.approvalRequests.length > 0;
    });
  }

  showCheckpoint(agentTaskId: string, checkpoint: CheckpointData) {
    this.updateAgent(agentTaskId, a => {
      // Same terminal guard as showApproval: a replayed checkpoint event must
      // not resurrect a checkpoint prompt on an already-finished task.
      if (a.status === 'completed' || a.status === 'failed') return;
      a.currentCheckpoint = checkpoint;
      a.showCheckpointPrompt = true;
      a.inlineCheckpoint = checkpoint;
      a.status = 'awaitingInput';
    });
  }

  hideCheckpoint(agentTaskId: string) {
    this.updateAgent(agentTaskId, a => {
      a.showCheckpointPrompt = false;
      a.currentCheckpoint = undefined;
      a.inlineCheckpoint = undefined;
    });
  }

  addToHistory(agentTaskId: string, item: AgentTaskHistoryItem) {
    this.updateAgent(agentTaskId, a => {
      // Enrich history item with current thinking and execution data if not already set
      if (!item.thinkingSegments && a.thinkingSegments.length > 0) {
        item.thinkingSegments = [...a.thinkingSegments];
      }
      if (!item.executionSteps && a.progressSteps.length > 0) {
        item.executionSteps = [...a.progressSteps];
      }
      if (!item.executionTimeline && a.executionTimeline.length > 0) {
        item.executionTimeline = [...a.executionTimeline];
      }
      if (!item.stepDetails && a.stepDetails.length > 0) {
        item.stepDetails = [...a.stepDetails];
      }
      if (!item.errorMessage && a.errorMessage) {
        item.errorMessage = a.errorMessage;
      }
      a.agentTaskHistory.push(item);
    });
  }

  setAgentTaskHistory(agentTaskId: string, items: AgentTaskHistoryItem[]) {
    this.updateAgent(agentTaskId, a => {
      a.agentTaskHistory = items;
    });
  }
}
