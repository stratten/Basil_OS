import {
  normalizePersistedThinkingSegments,
  type AgentTaskDetail,
  type AgentTaskHistoryItem,
  type DisplayableAgentTask,
} from '../types';

export function buildFollowUpHistoryFromViewedDetail(
  detail: DisplayableAgentTask
): AgentTaskHistoryItem[] {
  const history = [...detail.agentTaskHistory];
  const hasCurrentTurnContent = Boolean(detail.originalPrompt || detail.result || detail.errorMessage);
  const latestHistoryItem = history[history.length - 1];

  if (!hasCurrentTurnContent || latestHistoryItem?.id === detail.agentTaskId) {
    return history;
  }

  return [
    ...history,
    {
      id: detail.agentTaskId,
      agentTaskText: detail.originalPrompt,
      displayPromptMarkdown: detail.displayPromptMarkdown,
      originType: detail.currentTurnOriginType ?? (history.length === 0 ? detail.originType : undefined),
      originId: detail.currentTurnOriginType ? detail.currentTurnOriginId : (history.length === 0 ? detail.originId : undefined),
      result: detail.result,
      files: detail.structuredFiles,
      reference_paths: detail.referencePaths,
      timestamp: new Date().toISOString(),
      thinkingSegments: detail.thinkingSegments,
      executionSteps: detail.progressSteps,
      executionTimeline: detail.executionTimeline,
      stepDetails: detail.stepDetails,
      errorMessage: detail.errorMessage,
      outcome: detail.outcome,
      resultSeverity: detail.resultSeverity,
      status: detail.status,
      modelUsed: detail.modelUsed ?? detail.originalModelId,
    },
  ];
}

/**
 * Projects every durable turn that precedes an optimistic active follow-up.
 *
 * The active child can be absent from the response while its backend row is
 * still being committed, or present once that commit finishes. In both cases,
 * it must remain the live card rather than becoming a duplicate history item.
 */
export function buildDurableFollowUpHistoryBeforeActiveChild(
  detail: AgentTaskDetail,
  activeChildId: string,
): AgentTaskHistoryItem[] {
  const history: AgentTaskHistoryItem[] = [{
    id: detail.id,
    agentTaskText: detail.original_prompt,
    displayPromptMarkdown: detail.display_prompt_markdown,
    originType: detail.origin_type,
    originId: detail.origin_id,
    result: detail.result_message || '',
    files: detail.files || [],
    reference_paths: detail.reference_paths || [],
    timestamp: detail.timestamp,
    thinkingSegments: normalizePersistedThinkingSegments(detail.thinking_history),
    executionTimeline: detail.execution_timeline,
    errorMessage: detail.error_message,
    outcome: detail.outcome,
    resultSeverity: detail.result_severity,
    status: detail.status,
    modelUsed: detail.model_used ?? detail.model_id,
  }];

  for (const followUp of detail.follow_ups) {
    if (followUp.id === activeChildId) continue;
    history.push({
      id: followUp.id,
      agentTaskText: followUp.original_prompt,
      displayPromptMarkdown: followUp.display_prompt_markdown,
      originType: followUp.origin_type,
      originId: followUp.origin_id,
      result: followUp.result_message || '',
      files: followUp.files || [],
      reference_paths: followUp.reference_paths || [],
      timestamp: followUp.timestamp,
      thinkingSegments: normalizePersistedThinkingSegments(followUp.thinking_history),
      executionTimeline: followUp.execution_timeline,
      errorMessage: followUp.error_message,
      outcome: followUp.outcome,
      resultSeverity: followUp.result_severity,
      status: followUp.status,
      modelUsed: followUp.model_used ?? followUp.model_id,
    });
  }

  return history.filter(item => item.id !== activeChildId);
}
