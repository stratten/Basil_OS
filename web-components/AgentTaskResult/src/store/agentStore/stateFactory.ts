import type { AgentState } from '../../types';

export function createAgentState(agentTaskId: string, agentTaskText = ''): AgentState {
  return {
    agentTaskId,
    currentTurnTaskId: agentTaskId,
    originalPrompt: agentTaskText,
    status: 'routing',
    resultSeverity: 'neutral',
    result: '',
    delegatedProviderReportCards: [],
    structuredFiles: [],
    referencePaths: [],
    agentTaskHistory: [],
    progressSteps: [],
    showWorkflowPlan: false,
    isStreaming: false,
    isCanceling: false,
    isCanceled: false,
    cancellationError: undefined,
    hasUnreadResult: false,
    timestamp: new Date().toISOString(),
    approvalRequests: [],
    showApprovalPrompt: false,
    rememberApprovalChoice: false,
    seenApprovalIds: [],
    showCheckpointPrompt: false,
    checkpointAvailable: false,
    thinkingSegments: [],
    executionTimeline: [],
    stepDetails: [],
  };
}
