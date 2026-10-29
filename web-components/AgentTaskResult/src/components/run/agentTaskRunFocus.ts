import { deriveAgentTaskArtifacts } from '../artifacts/artifactDerivation';
import type { DisplayableAgentTask, ResultSeverity, StructuredFile, TimelineEntry } from '../../types';

export type AgentTaskRunKind = 'root' | 'follow_up';

export interface AgentTaskRunFocusSummary {
  id: string;
  kind: AgentTaskRunKind;
  ordinal: number;
  // Position among non-revision turns (1, 2, 3); an agent revision is `${parent}.${k}` (1.1, 2.1). This is what the rail and run map print.
  displayNumber: string;
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

// Numbers one turn per entry: non-revision turns count 1, 2, 3; an agent revision is `${parent}.${k}` for the nearest preceding non-revision turn.
export function agentTaskRunNumbers(originTypes: ReadonlyArray<string | undefined>): string[] {
  let primaryTurns = 0;
  let revisionsOfParent = 0;
  return originTypes.map((originType, index) => {
    if (index > 0 && originType === AGENT_REVISION_ORIGIN_TYPE) {
      revisionsOfParent += 1;
      return `${primaryTurns}.${revisionsOfParent}`;
    }
    primaryTurns += 1;
    revisionsOfParent = 0;
    return String(primaryTurns);
  });
}

// An agent revision's number carries a dot (1.1), which is what the rail and run map widen their badge for.
export function isRevisionNumber(displayNumber: string): boolean {
  return displayNumber.includes('.');
}

// Labels one turn per entry. User follow-ups are counted on their own and agent revisions carry the parent-based number, so an automatic turn is never mistaken for something the user asked and the label matches the rail.
export function agentTaskRunLabels(originTypes: ReadonlyArray<string | undefined>): string[] {
  const numbers = agentTaskRunNumbers(originTypes);
  let userFollowUps = 0;
  return originTypes.map((originType, index) => {
    if (index === 0) return 'Initial request';
    if (originType === AGENT_REVISION_ORIGIN_TYPE) return `Agent revision ${numbers[index]}`;
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

// Numbers every historical turn followed by the current turn, in display order.
export function agentTaskRunNumbersForTask(displaySource: DisplayableAgentTask): string[] {
  return agentTaskRunNumbers([
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
  const numbers = agentTaskRunNumbersForTask(displaySource);
  const historicalRuns = displaySource.agentTaskHistory.map((item, index) => ({
    id: item.id,
    kind: index === 0 ? 'root' as const : 'follow_up' as const,
    ordinal: index + 1,
    displayNumber: numbers[index],
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
      displayNumber: numbers[historicalRuns.length],
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
