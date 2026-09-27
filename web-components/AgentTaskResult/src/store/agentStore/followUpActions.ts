import type { AgentTaskHistoryItem, AgentState } from '../../types';
import { createAgentState } from './stateFactory';
import { AgentStoreCore } from './storeCore';

export class FollowUpAgentStore extends AgentStoreCore {
  registerFollowUp(followUpId: string, parentId: string, previousTaskId?: string) {
    const rootId = this.resolveCanonicalRootId(parentId);
    console.log(`[AgentStore] registerFollowUp: followUpId=${followUpId}, parentId=${parentId}, rootId=${rootId}, parentExists=${this.agents.has(rootId)}, selectedBefore=${this.selectedAgentId}`);
    this.beginFollowUpTurn(followUpId, rootId, undefined, previousTaskId);
    console.log(`[AgentStore] registerFollowUp complete: parentStatus=${this.agents.get(rootId)?.status}, selectedAfter=${this.selectedAgentId}`);
  }

  beginFollowUpTurn(
    followUpId: string,
    parentId: string,
    snapshot?: AgentTaskHistoryItem,
    previousTaskId?: string,
    initialTaskTitle?: string,
  ) {
    const rootId = this.resolveCanonicalRootId(parentId);
    const alreadyMapped = this.followUpToParent.get(followUpId) === rootId;
    console.log(`[AgentStore] beginFollowUpTurn: followUpId=${followUpId}, parentId=${parentId}, rootId=${rootId}, alreadyMapped=${alreadyMapped}`);
    this.followUpToParent.set(followUpId, rootId);
    this.activeFollowUpByParent.set(rootId, followUpId);
    if (!this.agents.has(rootId)) {
      const rootAgent = createAgentState(rootId, snapshot?.agentTaskText || '');
      rootAgent.taskTitle = initialTaskTitle?.trim() || undefined;
      this.agents.set(rootId, rootAgent);
    }
    this.agents.delete(followUpId);
    this.selectedAgentId = rootId;

    this.clearPendingStepTimer(rootId);
    this.stepDisplayTimes.delete(rootId);

    this.updateAgent(rootId, a => {
      if (!alreadyMapped) {
        const item = snapshot || this.createHistoryItemFromCurrentTurn(a);
        if (item && (item.agentTaskText || item.result || item.errorMessage)) {
          a.agentTaskHistory.push(item);
        }
      }
      a.currentTurnTaskId = followUpId;
      a.originalPrompt = '';
      a.result = '';
      a.presentationSummary = undefined;
      a.delegatedProviderReportCards = [];
      a.errorMessage = undefined;
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
      a.status = 'processing';
      a.rootTaskId = rootId;
      a.previousTaskId = previousTaskId || (parentId !== rootId ? parentId : a.previousTaskId);
    });
  }

  isFollowUp(agentTaskId: string): boolean {
    return this.followUpToParent.has(agentTaskId);
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

    return {
      id: agent.currentTurnTaskId || agent.agentTaskId,
      agentTaskText: agent.originalPrompt,
      displayPromptMarkdown: agent.displayPromptMarkdown,
      originType: agent.originType,
      originId: agent.originId,
      result: agent.result,
      files: [...agent.structuredFiles],
      reference_paths: [...agent.referencePaths],
      timestamp: new Date().toISOString(),
      thinkingSegments: [...agent.thinkingSegments],
      executionSteps: [...agent.progressSteps],
      executionTimeline: [...agent.executionTimeline],
      stepDetails: [...agent.stepDetails],
      errorMessage: agent.errorMessage,
      outcome: agent.outcome,
      resultSeverity: agent.resultSeverity,
      status: agent.status,
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
