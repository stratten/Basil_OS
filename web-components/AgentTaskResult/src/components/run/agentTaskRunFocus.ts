import { deriveAgentTaskArtifacts } from '../artifacts/artifactDerivation';
import type { DisplayableAgentTask, ResultSeverity, StructuredFile, TimelineEntry } from '../../types';

export type AgentTaskRunKind = 'root' | 'follow_up';

export interface AgentTaskRunFocusSummary {
  id: string;
  kind: AgentTaskRunKind;
  ordinal: number;
  label: string;
  requestText: string;
  resultText: string;
  timestamp: string;
  taskStatus: string;
  outcome?: string;
  resultSeverity?: ResultSeverity;
  isProcessing: boolean;
  documentCount: number;
  hasVerifiedArtifactOutput?: boolean;
  structuredFiles: StructuredFile[];
  executionTimeline: TimelineEntry[];
  modelUsed?: string;
}

// The backend `origin_type` recorded when Basil continues a task on its own (an outcome-check gap or a scheduled check-in) rather than the user asking.
export const AGENT_REVISION_ORIGIN_TYPE = 'agent_follow_up';

// Labels one turn per entry. User follow-ups and agent revisions are numbered separately so an automatic turn is never mistaken for something the user asked.
export function agentTaskRunLabels(originTypes: ReadonlyArray<string | undefined>): string[] {
  let userFollowUps = 0;
  let agentRevisions = 0;
  return originTypes.map((originType, index) => {
    if (index === 0) return 'Initial request';
    if (originType === AGENT_REVISION_ORIGIN_TYPE) {
      agentRevisions += 1;
      return `Agent revision ${agentRevisions}`;
    }
    userFollowUps += 1;
    return `Follow-up ${userFollowUps}`;
  });
}

// Labels every historical turn followed by the current turn, in display order.
export function agentTaskRunLabelsForTask(displaySource: DisplayableAgentTask): string[] {
  return agentTaskRunLabels([
    ...displaySource.agentTaskHistory.map(item => item.originType),
    displaySource.currentTurnOriginType,
  ]);
}

function documentCount(files: StructuredFile[], timeline: TimelineEntry[]): number {
  return deriveAgentTaskArtifacts(files, timeline).produced.length;
}

function hasVerifiedArtifactOutput(files: StructuredFile[], timeline: TimelineEntry[]): boolean {
  return deriveAgentTaskArtifacts(files, timeline).produced.some(
    artifact => artifact.verification.status === 'verified',
  );
}

export function deriveAgentTaskRunFocusSummaries(
  displaySource: DisplayableAgentTask,
  isProcessing: boolean,
): AgentTaskRunFocusSummary[] {
  const labels = agentTaskRunLabelsForTask(displaySource);
  const historicalRuns = displaySource.agentTaskHistory.map((item, index) => ({
    id: item.id,
    kind: index === 0 ? 'root' as const : 'follow_up' as const,
    ordinal: index + 1,
    label: labels[index],
    requestText: item.agentTaskText,
    resultText: item.result,
    timestamp: item.timestamp,
    taskStatus: item.status ?? 'completed',
    outcome: item.outcome,
    resultSeverity: item.resultSeverity,
    isProcessing: false,
    documentCount: documentCount(item.files, item.executionTimeline || []),
    hasVerifiedArtifactOutput: hasVerifiedArtifactOutput(item.files, item.executionTimeline || []),
    structuredFiles: item.files,
    executionTimeline: item.executionTimeline || [],
    modelUsed: item.modelUsed,
  }));
  const ordinal = historicalRuns.length + 1;

  return [
    ...historicalRuns,
    {
      id: displaySource.currentTurnTaskId || displaySource.agentTaskId,
      kind: historicalRuns.length === 0 ? 'root' : 'follow_up',
      ordinal,
      label: labels[historicalRuns.length],
      requestText: displaySource.originalPrompt,
      resultText: displaySource.result,
      timestamp: displaySource.timestamp || '',
      taskStatus: displaySource.isCanceled ? 'canceled' : displaySource.status,
      outcome: displaySource.outcome,
      resultSeverity: displaySource.resultSeverity,
      isProcessing,
      documentCount: documentCount(displaySource.structuredFiles, displaySource.executionTimeline),
      hasVerifiedArtifactOutput: hasVerifiedArtifactOutput(
        displaySource.structuredFiles,
        displaySource.executionTimeline,
      ),
      structuredFiles: displaySource.structuredFiles,
      executionTimeline: displaySource.executionTimeline,
      modelUsed: displaySource.modelUsed ?? displaySource.originalModelId,
    },
  ];
}

export function resolveFocusedRun(
  runs: AgentTaskRunFocusSummary[],
  focusedRunId: string | undefined,
): AgentTaskRunFocusSummary {
  const fallback = runs[runs.length - 1];
  if (!fallback) {
    throw new Error('A displayable Agent Task must contain a current run.');
  }
  return runs.find(run => run.id === focusedRunId) || fallback;
}
