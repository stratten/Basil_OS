import type { AgentTaskHistoryItem, AgentState } from '../../types';
import { discardComposerDraft } from '../composerDraftStore';
import { upsertHistoryItem } from './historyIdentity';
import { createAgentState } from './stateFactory';
import { AgentStoreCore } from './storeCore';

export class FollowUpAgentStore extends AgentStoreCore {
  registerFollowUp(followUpId: string, parentId: string, previousTaskId?: string) {
    const rootId = this.resolveCanonicalRootId(parentId);
    console.log(`[AgentStore] registerFollowUp: followUpId=${followUpId}, parentId=${parentId}, rootId=${rootId}, parentExists=${this.agents.has(rootId)}, selectedBefore=${this.selectedAgentId}`);
    this.beginFollowUpTurn(followUpId, rootId, undefined, previousTaskId, undefined, { readerStarted: true });
    console.log(`[AgentStore] registerFollowUp complete: parentStatus=${this.agents.get(rootId)?.status}, selectedAfter=${this.selectedAgentId}`);
  }

  beginFollowUpTurn(
    followUpId: string,
    parentId: string,
    snapshot?: AgentTaskHistoryItem,
    previousTaskId?: string,
    initialTaskTitle?: string,
    options: { background?: boolean; readerStarted?: boolean } = {},
  ) {
    // A turn Basil started on its own (a scheduled run that continues the chain, or Basil continuing its own task) is not an answer to anything the reader typed and is not where they chose to be, so it leaves their view and their unsent text alone.
    const background = options.background === true;
    // Only a caller that knows the reader sent this turn (typed, or captured by voice) may discard their unsent text. A page that first meets a turn through a live event, or loads one from history, cannot tell a turn Basil started from one the reader started, and a window loaded mid-run never sees the origin event, so the safe default is to keep the text.
    const readerStarted = options.readerStarted === true && !background;
    const rootId = this.resolveCanonicalRootId(parentId);
    const alreadyMapped = this.followUpToParent.get(followUpId) === rootId;
    console.log(`[AgentStore] beginFollowUpTurn: followUpId=${followUpId}, parentId=${parentId}, rootId=${rootId}, alreadyMapped=${alreadyMapped}`);
    this.followUpToParent.set(followUpId, rootId);
    // A turn the reader started stays the active one: its terminal events must not be dropped as stale because Basil's own turn began beside it.
    if (!background || !this.activeFollowUpByParent.has(rootId)) {
      this.activeFollowUpByParent.set(rootId, followUpId);
    }
    // A turn the reader sent answers whatever they had typed for the next follow-up, so the unsent text must not outlive it.
    if (!alreadyMapped && readerStarted) {
      discardComposerDraft('follow-up', rootId);
      if (parentId !== rootId) discardComposerDraft('follow-up', parentId);
    }
    if (!this.agents.has(rootId)) {
      const rootAgent = createAgentState(rootId, snapshot?.agentTaskText || '');
      rootAgent.taskTitle = initialTaskTitle?.trim() || undefined;
      this.agents.set(rootId, rootAgent);
    }
    this.agents.delete(followUpId);
    if (!background) this.selectedAgentId = rootId;

    this.clearPendingStepTimer(rootId);
    this.stepDisplayTimes.delete(rootId);

    this.updateAgent(rootId, a => {
      if (!alreadyMapped) {
        const item = snapshot || this.createHistoryItemFromCurrentTurn(a);
        if (item && (item.agentTaskText || item.result || item.errorMessage)) {
          // A new array, not a push: the turn list is a dependency of memoized views (the open/closed state of each earlier turn is pruned against it), and an in-place push leaves them holding the old list, so the turn just snapshotted could not be opened until the chain was reloaded.
          a.agentTaskHistory = upsertHistoryItem(a.agentTaskHistory, item);
        }
      }
      a.currentTurnTaskId = followUpId;
      a.currentTurnOriginType = undefined;
      a.currentTurnOriginId = undefined;
      a.originalPrompt = '';
      // The request block shows displayPromptMarkdown ahead of originalPrompt, so a previous follow-up's rendering left in place would appear as soon as the new turn's transcription arrives. The references belong to the turn that was just snapshotted too.
      a.displayPromptMarkdown = undefined;
      a.referencePaths = [];
      a.connectionReferences = undefined;
      a.modelUsed = undefined;
      a.result = '';
      a.presentationSummary = undefined;
      a.delegatedProviderReportCards = [];
      a.errorMessage = undefined;
      a.suggestedFollowUps = undefined;
      a.structuredFiles = [];
      a.progressSteps = [];
      a.executionTimeline = [];
      a.stepDetails = [];
      a.currentStep = undefined;
      a.workflowPlan = undefined;
      a.showWorkflowPlan = false;
      a.isStreaming = false;
      a.thinking = undefined;
      a.thinkingComplete = undefined;
      a.thinkingSegments = [];
      a.checkpointAvailable = false;
      a.inlineCheckpoint = undefined;
      a.currentCheckpoint = undefined;
      a.showCheckpointPrompt = false;
      a.showApprovalPrompt = false;
      a.approvalRequests = [];
      a.showTokenConnectPrompt = false;
      a.tokenConnectRequest = undefined;
      // Cancellation belongs to the turn that was canceled. Left set it stays on the card, and the live-event gate in handleWSEvent drops every event for the new turn as "after cancellation".
      a.isCanceled = false;
      a.isCanceling = false;
      a.cancellationError = undefined;
      a.status = 'processing';
      a.rootTaskId = rootId;
      a.previousTaskId = previousTaskId || (parentId !== rootId ? parentId : a.previousTaskId);
    });
  }

  isFollowUp(agentTaskId: string): boolean {
    return this.followUpToParent.has(agentTaskId);
  }

  /**
   * The id of the entry this window already holds for a task, or undefined when it holds none.
   *
   * That is the task's own entry, or the chain root that carries it as a turn. A follow-up turn has no entry of its own, so a plain lookup by the turn's id misses it, and opening it as if it were new would start a second, separate entry for a task the window already shows. The turn is recognized by the follow-up mapping, as the turn on display, or as an earlier turn in the root's history.
   */
  findOpenEntryForTask(taskId: string): string | undefined {
    if (this.agents.has(taskId)) return taskId;
    if (this.followUpToParent.has(taskId)) {
      const rootId = this.resolveCanonicalRootId(taskId);
      if (this.agents.has(rootId)) return rootId;
    }
    for (const [entryId, agent] of this.agents) {
      if (agent.currentTurnTaskId === taskId || agent.agentTaskHistory.some(turn => turn.id === taskId)) return entryId;
    }
    return undefined;
  }

  // A follow-up turn has no state of its own: beginFollowUpTurn deletes it and the chain root carries the displayed turn. Writing to the follow-up's id would be a silent no-op, so files attached to a voice follow-up are recorded on the root here.
  setCurrentTurnReferencePaths(turnTaskId: string, paths: string[]) {
    this.updateAgent(this.resolveCanonicalRootId(turnTaskId), a => {
      a.referencePaths = [...paths];
    });
  }

  setPendingFollowUpParent(parentId: string) {
    console.log(`[AgentStore] setPendingFollowUpParent: ${parentId}`);
    this.pendingFollowUpParent = parentId;
  }

  consumePendingFollowUpParent(): string | null {
    const p = this.pendingFollowUpParent;
    this.pendingFollowUpParent = null;
    console.log(`[AgentStore] consumePendingFollowUpParent: ${p ?? 'null'}`);
    return p;
  }

  protected createHistoryItemFromCurrentTurn(agent: AgentState): AgentTaskHistoryItem | undefined {
    if (!agent.originalPrompt && !agent.result && !agent.errorMessage) {
      return undefined;
    }

    // The root turn owns `originType`; a later turn carries its own provenance, so a follow-up never inherits the root's origin.
    const snapshotsRootTurn = (agent.currentTurnTaskId || agent.agentTaskId) === agent.agentTaskId;
    return {
      id: agent.currentTurnTaskId || agent.agentTaskId,
      agentTaskText: agent.originalPrompt,
      displayPromptMarkdown: agent.displayPromptMarkdown,
      originType: snapshotsRootTurn ? agent.originType : agent.currentTurnOriginType,
      originId: snapshotsRootTurn ? agent.originId : agent.currentTurnOriginId,
      result: agent.result,
      files: [...agent.structuredFiles],
      reference_paths: [...agent.referencePaths],
      connection_references: agent.connectionReferences ? [...agent.connectionReferences] : undefined,
      timestamp: new Date().toISOString(),
      thinkingSegments: [...agent.thinkingSegments],
      executionSteps: [...agent.progressSteps],
      executionTimeline: [...agent.executionTimeline],
      stepDetails: [...agent.stepDetails],
      errorMessage: agent.errorMessage,
      outcome: agent.outcome,
      resultSeverity: agent.resultSeverity,
      status: agent.status,
      modelUsed: agent.modelUsed ?? agent.originalModelId,
    };
  }

  // Public: the App.tsx self-healing poll (hydrateActiveFollowUpChild in
  // agentHydration.ts) clears this directly once it has applied a missed
  // terminal result for the active child, so subsequent root hydrations
  // are no longer suppressed by the "ignore terminal parent while a
  // follow-up is active" guard in agentHydration.ts.
  clearActiveFollowUpTurn(parentId: string, followUpId?: string) {
    const activeFollowUpId = this.activeFollowUpByParent.get(parentId);
    if (!activeFollowUpId) return;
    if (followUpId && activeFollowUpId !== followUpId) return;
    this.activeFollowUpByParent.delete(parentId);
  }

  setRootTaskId(agentTaskId: string, rootId: string) {
    this.updateAgent(agentTaskId, a => {
      a.rootTaskId = rootId;
    });
  }

  protected resolveCanonicalRootId(taskId: string): string {
    let current = taskId;
    const seen = new Set<string>();
    while (this.followUpToParent.has(current) && !seen.has(current)) {
      seen.add(current);
      current = this.followUpToParent.get(current)!;
    }
    const agent = this.agents.get(current);
    return agent?.rootTaskId || current;
  }

  protected recordChainIdentity(agentTaskId: string, rootTaskId?: string, previousTaskId?: string) {
    this.updateAgent(agentTaskId, a => {
      if (rootTaskId) {
        a.rootTaskId = rootTaskId;
      }
      if (previousTaskId) {
        a.previousTaskId = previousTaskId;
      }
    });
  }
}
