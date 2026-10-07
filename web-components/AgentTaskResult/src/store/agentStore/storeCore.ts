import type {
  AgentState,
  AgentStatus,
} from '../../types';
import { createAgentState } from './stateFactory';

export type Listener = () => void;

export class AgentStoreCore {
  protected agents: Map<string, AgentState> = new Map();
  protected selectedAgentId: string | null = null;
  protected listeners: Set<Listener> = new Set();
  protected version = 0;
  protected agentVersions: Map<string, number> = new Map();
  protected agentListeners: Map<string, Set<Listener>> = new Map();
  protected followUpToParent: Map<string, string> = new Map();
  protected activeFollowUpByParent: Map<string, string> = new Map();
  protected pendingFollowUpParent: string | null = null;
  protected transientAgentIds: Set<string> = new Set();

  // Step display throttling (matches Swift's ProgressManager minimumDisplayDuration)
  protected stepDisplayTimes: Map<string, number> = new Map();
  protected pendingStepTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();

  protected emit() {
    this.version++;
    for (const l of this.listeners) l();
  }

  protected emitAgent(agentTaskId: string) {
    const nextVersion = (this.agentVersions.get(agentTaskId) ?? 0) + 1;
    this.agentVersions.set(agentTaskId, nextVersion);
    const listeners = this.agentListeners.get(agentTaskId);
    if (listeners) {
      for (const listener of listeners) listener();
    }
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  subscribeToAgent(agentTaskId: string, listener: Listener): () => void {
    let listeners = this.agentListeners.get(agentTaskId);
    if (!listeners) {
      listeners = new Set();
      this.agentListeners.set(agentTaskId, listeners);
    }
    listeners.add(listener);
    return () => {
      listeners?.delete(listener);
      if (listeners?.size === 0) this.agentListeners.delete(agentTaskId);
    };
  }

  getSnapshot(): number {
    return this.version;
  }

  getAgentVersion(agentTaskId: string): number {
    return this.agentVersions.get(agentTaskId) ?? 0;
  }

  // --- Accessors ---

  getAgent(agentTaskId: string): AgentState | undefined {
    return this.agents.get(agentTaskId);
  }

  getSelectedAgent(): AgentState | undefined {
    if (!this.selectedAgentId) return undefined;
    return this.agents.get(this.selectedAgentId);
  }

  getSelectedAgentId(): string | null {
    return this.selectedAgentId;
  }

  getAllAgents(): AgentState[] {
    return Array.from(this.agents.values());
  }

  getActiveAgents(): AgentState[] {
    return this.getAllAgents().filter(
      a => a.status === 'routing' || a.status === 'processing' || a.status === 'awaitingInput' || a.status === 'capturing'
    );
  }

  getCompletedAgents(): AgentState[] {
    return this.getAllAgents().filter(
      a => a.status === 'completed' || a.status === 'failed'
    );
  }

  getActiveFollowUpId(parentId: string): string | undefined {
    return this.activeFollowUpByParent.get(parentId);
  }

  getCurrentTurnTaskId(rootTaskId: string): string {
    const canonicalRootId = this.followUpToParent.get(rootTaskId) || rootTaskId;
    return this.activeFollowUpByParent.get(canonicalRootId)
      || this.agents.get(canonicalRootId)?.currentTurnTaskId
      || canonicalRootId;
  }

  hasActiveFollowUpTurn(parentId: string): boolean {
    return this.activeFollowUpByParent.has(parentId);
  }

  // --- Mutations ---

  selectAgent(agentTaskId: string) {
    if (this.agents.has(agentTaskId)) {
      this.selectedAgentId = agentTaskId;
      const agent = this.agents.get(agentTaskId)!;
      agent.hasUnreadResult = false;
      this.emit();
    }
  }

  deselectAgent() {
    this.selectedAgentId = null;
    this.emit();
  }

  registerAgent(agentTaskId: string, agentTaskText = '') {
    if (!this.agents.has(agentTaskId)) {
      console.log(`[AgentStore] registerAgent: NEW agent ${agentTaskId}, agentTask='${agentTaskText.substring(0, 40)}', agentCount=${this.agents.size + 1}, selected=${this.selectedAgentId}`);
      this.agents.set(agentTaskId, createAgentState(agentTaskId, agentTaskText));
      if (!this.selectedAgentId) {
        this.selectedAgentId = agentTaskId;
      }
      this.emit();
      this.emitAgent(agentTaskId);
    }
  }

  removeAgent(agentTaskId: string) {
    this.agents.delete(agentTaskId);
    this.transientAgentIds.delete(agentTaskId);
    if (this.selectedAgentId === agentTaskId) {
      const remaining = this.getAllAgents();
      this.selectedAgentId = remaining.length > 0 ? remaining[remaining.length - 1].agentTaskId : null;
    }
    this.emit();
    this.emitAgent(agentTaskId);
  }

  markTransientAgent(agentTaskId: string) {
    this.transientAgentIds.add(agentTaskId);
  }

  clearTransientAgent(agentTaskId: string) {
    this.transientAgentIds.delete(agentTaskId);
  }

  isTransientWithoutDurableData(agentTaskId: string): boolean {
    const agent = this.agents.get(agentTaskId);
    if (!agent || !this.transientAgentIds.has(agentTaskId)) return false;
    return !agent.originalPrompt &&
      !agent.result &&
      !agent.errorMessage &&
      agent.executionTimeline.length === 0 &&
      agent.stepDetails.length === 0;
  }

  /**
   * Resolve a provisional agent_task_id whose backend record will never
   * exist (no-speech transcription, /process-audio failure, network
   * error, etc.).
   *
   * - If the row is still transient and has no durable data, it is
   *   removed entirely so the sidebar doesn't show a ghost
   *   "Processing..." entry and ``App.tsx``'s polling loop can stop
   *   chasing the never-persisted ID.
   * - Otherwise the row already accumulated durable content (e.g., the
   *   user typed something into the original-prompt area, partial
   *   thinking arrived, etc.), so we mark it failed with the supplied
   *   message and emit terminal status to silence the poller.
   *
   * Returns ``true`` if the row was removed, ``false`` if marked failed
   * (or no row was present to act on).
   */
  handleProvisionalFailure(agentTaskId: string, message: string): boolean {
    const agent = this.agents.get(agentTaskId);
    if (!agent) {
      // Nothing to do, but still clear any leftover transient marker so
      // a future re-registration with the same ID isn't accidentally
      // treated as a leftover transient.
      this.transientAgentIds.delete(agentTaskId);
      return false;
    }
    if (this.isTransientWithoutDurableData(agentTaskId)) {
      console.log(
        `[AgentStore] handleProvisionalFailure: removing transient ${agentTaskId} (${message})`
      );
      this.removeAgent(agentTaskId);
      return true;
    }
    console.log(
      `[AgentStore] handleProvisionalFailure: marking ${agentTaskId} as failed (${message})`
    );
    this.transientAgentIds.delete(agentTaskId);
    this.updateAgent(agentTaskId, a => {
      a.status = 'failed';
      a.isStreaming = false;
      a.errorMessage = message;
      a.currentStep = undefined;
    });
    return false;
  }

  protected updateAgent(agentTaskId: string, updater: (agent: AgentState) => void) {
    const agent = this.agents.get(agentTaskId);
    if (!agent) return;
    updater(agent);
    if (agentTaskId !== this.selectedAgentId) {
      agent.hasUnreadResult = true;
    }
    this.emit();
    this.emitAgent(agentTaskId);
  }

  protected isAgentCanceled(agentTaskId: string): boolean {
    return this.agents.get(agentTaskId)?.isCanceled === true;
  }

  markCanceled(agentTaskId: string) {
    this.updateAgent(agentTaskId, a => {
      a.isCanceled = true;
      a.isCanceling = false;
    });
  }

  protected clearPendingStepTimer(agentTaskId: string) {
    const existing = this.pendingStepTimers.get(agentTaskId);
    if (existing) {
      clearTimeout(existing);
      this.pendingStepTimers.delete(agentTaskId);
    }
  }

  updateStatus(agentTaskId: string, status: AgentStatus) {
    if (this.isAgentCanceled(agentTaskId)) return;
    this.updateAgent(agentTaskId, a => {
      if ((a.status === 'completed' || a.status === 'failed') && status !== 'completed' && status !== 'failed') {
        return;
      }
      a.status = status;
      // A terminal task cannot still be awaiting approval/checkpoint input.
      // Clear any pending prompt so a stale overlay (e.g. resolved in another
      // window, or replayed when a window reopens) does not linger, and so the
      // sidebar's needs-approval badge reflects the finished state across both
      // the main and detached components.
      if (status === 'completed' || status === 'failed') {
        a.isRetryPending = false;
        a.showApprovalPrompt = false;
        a.approvalRequests = [];
        a.showCheckpointPrompt = false;
        a.currentCheckpoint = undefined;
        a.inlineCheckpoint = undefined;
      }
    });
  }

  markCheckpointResumeProcessing(agentTaskId: string, step = 'Resuming...') {
    if (this.isAgentCanceled(agentTaskId)) return;
    this.clearPendingStepTimer(agentTaskId);
    this.updateAgent(agentTaskId, a => {
      a.status = 'processing';
      a.errorMessage = undefined;
      a.isStreaming = false;
      a.currentStep = step;
      a.checkpointAvailable = false;
      a.showCheckpointPrompt = false;
      a.currentCheckpoint = undefined;
      a.inlineCheckpoint = undefined;
    });
  }

  updateAgentTaskText(agentTaskId: string, agentTaskText: string) {
    this.updateAgent(agentTaskId, a => { a.originalPrompt = agentTaskText; });
  }

  updateAgentDisplayPromptMarkdown(agentTaskId: string, displayPromptMarkdown: string | undefined) {
    this.updateAgent(agentTaskId, a => { a.displayPromptMarkdown = displayPromptMarkdown; });
  }

  setCurrentTurnTaskId(agentTaskId: string, currentTurnTaskId: string) {
    this.updateAgent(agentTaskId, a => { a.currentTurnTaskId = currentTurnTaskId; });
  }

  updateAgentTaskTitle(agentTaskId: string, taskTitle: string | undefined) {
    const normalizedTitle = taskTitle?.trim();
    if (!normalizedTitle) return;
    this.updateAgent(agentTaskId, a => {
      if (!a.taskTitle) {
        a.taskTitle = normalizedTitle;
      }
    });
  }

  updateAgentOrigin(agentTaskId: string, originType: string | undefined, originId: string | undefined) {
    if (!originType && !originId) return;
    this.updateAgent(agentTaskId, a => {
      a.originType = originType;
      a.originId = originId;
    });
  }

  updateReasoningFallbackModelUsed(agentTaskId: string, reasoningFallbackModelUsed: string | undefined) {
    if (!reasoningFallbackModelUsed) return;
    this.updateAgent(agentTaskId, a => {
      a.reasoningFallbackModelUsed = reasoningFallbackModelUsed;
    });
  }

  updateOriginalModelId(agentTaskId: string, originalModelId: string | undefined) {
    if (!originalModelId) return;
    this.updateAgent(agentTaskId, a => {
      a.originalModelId = originalModelId;
    });
  }

  // Sticky across the retry model selector (ResultContent) and TextFollowUp's
  // own picker -- whichever surface the user last touched wins as the
  // default for the other. No-op if the agent is not yet registered in the
  // store (updateAgent already guards on that).
  setSelectedModelId(agentTaskId: string, selectedModelId: string | undefined) {
    this.updateAgent(agentTaskId, a => {
      a.selectedModelId = selectedModelId;
    });
  }
}
