import type {
  AgentStatus,
  AgentTaskDetail,
  AgentTaskHistoryItem,
  DisplayableAgentTask,
} from '../../types';
import { normalizePersistedThinkingSegments } from '../../types';
import { parseAgentTaskPresentationSummaryForTask } from '../../artifacts/artifactContract';
import { detailsFromTimeline } from '../../store/agentStore';
import { plainMarkdownText } from '../../../../shared/plainMarkdownText';

export function mapBackendStatus(status: string): AgentStatus {
  switch (status) {
    case 'routing':
    case 'processing':
    case 'capturing':
    case 'completed':
    case 'failed':
      return status;
    case 'awaiting_user_input':
      return 'awaitingInput';
    case 'canceled':
      return 'failed';
    default:
      return 'completed';
  }
}

export function mapDetailToDisplayable(detail: AgentTaskDetail): DisplayableAgentTask {
  if (detail.follow_ups && detail.follow_ups.length > 0) {
    const mostRecent = detail.follow_ups[detail.follow_ups.length - 1];
    const historyItems: AgentTaskHistoryItem[] = [
      {
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
        stepDetails: detail.execution_timeline ? detailsFromTimeline(detail.execution_timeline) : [],
        errorMessage: detail.error_message,
        outcome: detail.outcome,
        resultSeverity: detail.result_severity,
        status: mapBackendStatus(detail.status),
      },
      ...detail.follow_ups.slice(0, -1).map(fu => ({
        id: fu.id,
        agentTaskText: fu.original_prompt,
        displayPromptMarkdown: fu.display_prompt_markdown,
        originType: detail.origin_type,
        originId: detail.origin_id,
        result: fu.result_message || '',
        files: fu.files || [],
        reference_paths: fu.reference_paths || [],
        timestamp: fu.timestamp,
        thinkingSegments: normalizePersistedThinkingSegments(fu.thinking_history),
        executionTimeline: fu.execution_timeline,
        stepDetails: fu.execution_timeline ? detailsFromTimeline(fu.execution_timeline) : [],
        errorMessage: fu.error_message,
        outcome: fu.outcome,
        resultSeverity: fu.result_severity,
        status: mapBackendStatus(fu.status),
      })),
    ];

    const status = mapBackendStatus(mostRecent.status);
    const isTerminal = status === 'completed' || status === 'failed';
    const presentationSummary = parseAgentTaskPresentationSummaryForTask(
      mostRecent.id,
      mostRecent.agent_task_presentation_summary,
    );
    const parentPresentationSummary = parseAgentTaskPresentationSummaryForTask(
      detail.id,
      detail.agent_task_presentation_summary,
    );
    return {
      agentTaskId: mostRecent.id,
      rootTaskId: mostRecent.root_task_id || detail.root_task_id || detail.id,
      previousTaskId: mostRecent.previous_task_id,
      currentTurnTaskId: mostRecent.id,
      timestamp: mostRecent.timestamp,
      originType: detail.origin_type,
      originId: detail.origin_id,
      originalPrompt: mostRecent.original_prompt,
      displayPromptMarkdown: mostRecent.display_prompt_markdown || mostRecent.original_prompt || '',
      taskTitle: detail.title,
      status,
      result: isTerminal ? (mostRecent.result_message || '') : '',
      errorMessage: status === 'failed'
        ? (mostRecent.error_message || mostRecent.result_message || 'Task failed')
        : undefined,
      outcome: mostRecent.outcome,
      resultSeverity: mostRecent.result_severity,
      presentationSummary,
      delegatedProviderReportCards: parentPresentationSummary?.delegatedProviderReportCards
        ?? presentationSummary?.delegatedProviderReportCards
        ?? [],
      structuredFiles: mostRecent.files || [],
      referencePaths: mostRecent.reference_paths || [],
      agentTaskHistory: historyItems,
      progressSteps: [],
      executionTimeline: mostRecent.execution_timeline || [],
      stepDetails: detailsFromTimeline(mostRecent.execution_timeline || []),
      showWorkflowPlan: false,
      isStreaming: false,
      checkpointAvailable: false,
      thinkingSegments: normalizePersistedThinkingSegments(mostRecent.thinking_history),
      originalModelId: mostRecent.model_id,
    };
  }

  const status = mapBackendStatus(detail.status);
  const isTerminal = status === 'completed' || status === 'failed';
  const presentationSummary = parseAgentTaskPresentationSummaryForTask(
    detail.id,
    detail.agent_task_presentation_summary,
  );
  return {
    agentTaskId: detail.id,
    rootTaskId: detail.root_task_id || detail.id,
    previousTaskId: detail.previous_task_id,
    currentTurnTaskId: detail.id,
    timestamp: detail.timestamp,
    originType: detail.origin_type,
    originId: detail.origin_id,
    originalPrompt: detail.original_prompt,
    displayPromptMarkdown: detail.display_prompt_markdown,
    taskTitle: detail.title,
    status,
    result: isTerminal ? (detail.result_message || '') : '',
    errorMessage: status === 'failed'
      ? (detail.error_message || detail.result_message || 'Task failed')
      : undefined,
    outcome: detail.outcome,
    resultSeverity: detail.result_severity,
    presentationSummary,
    delegatedProviderReportCards: presentationSummary?.delegatedProviderReportCards ?? [],
    structuredFiles: detail.files || [],
    referencePaths: detail.reference_paths || [],
    agentTaskHistory: [],
    progressSteps: [],
    executionTimeline: detail.execution_timeline || [],
    stepDetails: detailsFromTimeline(detail.execution_timeline || []),
    showWorkflowPlan: false,
    isStreaming: false,
    checkpointAvailable: false,
    thinkingSegments: normalizePersistedThinkingSegments(detail.thinking_history),
    originalModelId: detail.model_id,
  };
}

export function truncateTitle(text: string, max = 40): string {
  if (text.length <= max) return text;
  return text.substring(0, max) + '...';
}

export function plainSidebarText(markdown: string): string {
  return plainMarkdownText(markdown);
}

export function stripStepMarkers(preview: string): string {
  return preview
    .split('\n')
    .filter(line => {
      const t = line.trim();
      return !t.startsWith('STEP_START:') && !t.startsWith('STEP_COMPLETE:') && !t.startsWith('FAIL_NOTE:');
    })
    .join('\n')
    .trim();
}
