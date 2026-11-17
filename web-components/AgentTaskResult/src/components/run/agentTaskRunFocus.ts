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

// The backend `origin_type` recorded when Basil amends a run on its own because the outcome check found a gap. Only this kind of turn is a revision.
export const AGENT_REVISION_ORIGIN_TYPE = 'agent_follow_up';

// The backend `origin_type` recorded when a check the agent scheduled for itself comes due. It is a new turn in the chain, not an amendment, so it is never called a revision and carries no number.
export const SCHEDULED_CHECK_ORIGIN_TYPE = 'scheduled_follow_up';

// Numbers one turn per entry: non-revision turns count 1, 2, 3; an agent revision is `${parent}.${k}` for the nearest preceding non-revision turn; a scheduled check has no number (an empty string) and does not count toward the others.
export function agentTaskRunNumbers(originTypes: ReadonlyArray<string | undefined>): string[] {
  let primaryTurns = 0;
  let revisionsOfParent = 0;
  return originTypes.map((originType, index) => {
    if (index > 0 && originType === SCHEDULED_CHECK_ORIGIN_TYPE) return '';
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

// Labels one turn per entry. User follow-ups are counted on their own. An agent revision is named for the turn it revises ("Agent revision 2 of Follow-up 4") and a scheduled check for the turn that asked for it ("Scheduled check 3 of Follow-up 4"), so an automatic turn is never mistaken for something the user asked and its label points at text that is visible in the same chain. Revisions and scheduled checks each count up from 1 within one turn.
export function agentTaskRunLabels(originTypes: ReadonlyArray<string | undefined>): string[] {
  let userFollowUps = 0;
  let revisedTurnName = 'the initial request';
  let revisionsOfTurn = 0;
  let scheduledChecksOfTurn = 0;
  return originTypes.map((originType, index) => {
    if (index === 0) return 'Initial request';
    if (originType === SCHEDULED_CHECK_ORIGIN_TYPE) {
      scheduledChecksOfTurn += 1;
      return `Scheduled check ${scheduledChecksOfTurn} of ${revisedTurnName}`;
    }
    if (originType === AGENT_REVISION_ORIGIN_TYPE) {
      revisionsOfTurn += 1;
      return `Agent revision ${revisionsOfTurn} of ${revisedTurnName}`;
    }
    userFollowUps += 1;
    revisedTurnName = `Follow-up ${userFollowUps}`;
    revisionsOfTurn = 0;
    scheduledChecksOfTurn = 0;
    return revisedTurnName;
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
