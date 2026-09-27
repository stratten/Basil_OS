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
  const historicalRuns = displaySource.agentTaskHistory.map((item, index) => ({
    id: item.id,
    kind: index === 0 ? 'root' as const : 'follow_up' as const,
    ordinal: index + 1,
    label: index === 0 ? 'Initial request' : `Follow-up ${index}`,
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
  }));
  const ordinal = historicalRuns.length + 1;

  return [
    ...historicalRuns,
    {
      id: displaySource.currentTurnTaskId || displaySource.agentTaskId,
      kind: historicalRuns.length === 0 ? 'root' : 'follow_up',
      ordinal,
      label: historicalRuns.length === 0 ? 'Initial request' : `Follow-up ${historicalRuns.length}`,
      requestText: displaySource.originalPrompt,
      resultText: displaySource.result,
      timestamp: displaySource.timestamp || '',
      taskStatus: displaySource.status,
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
