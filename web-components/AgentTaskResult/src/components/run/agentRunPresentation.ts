import type { TimelineEntry } from '../../types';

export type AgentRunStageKind = 'phase' | 'tool' | 'artifact' | 'outcome';
export type AgentRunStageState = 'active' | 'completed' | 'failed' | 'waiting' | 'recorded';

export interface AgentRunStage {
  id: string;
  kind: AgentRunStageKind;
  label: string;
  state: AgentRunStageState;
  startedAt: string;
  completedAt?: string;
  artifactId?: string;
  phase?: string;
}

export interface AgentRunPresentation {
  stages: AgentRunStage[];
  terminalState: 'active' | 'completed' | 'failed';
}

type IndexedTimelineEntry = {
  entry: TimelineEntry;
  index: number;
};

function timelineStatus(entry: TimelineEntry): string | undefined {
  const metadataStatus = entry.metadata?.progress_status ?? entry.metadata?.status;
  return typeof metadataStatus === 'string' && metadataStatus.trim() ? metadataStatus.trim().toLowerCase() : undefined;
}

function stageState(status: string | undefined, fallback: AgentRunStageState): AgentRunStageState {
  if (status === 'completed') return 'completed';
  if (status === 'failed' || status === 'error' || status === 'canceled') return 'failed';
  if (status === 'waiting_user_input' || status === 'blocked') return 'waiting';
  if (status === 'started' || status === 'running' || status === 'in_progress') return 'active';
  return fallback;
}

function userFacingLabel(entry: TimelineEntry, fallback: string): string {
  const label = entry.summary || entry.content || fallback;
  return label.trim() || fallback;
}

function stableChronologicalEntries(timeline: TimelineEntry[]): IndexedTimelineEntry[] {
  return timeline
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => {
      const leftTime = Date.parse(left.entry.timestamp);
      const rightTime = Date.parse(right.entry.timestamp);
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return leftTime - rightTime;
      if (Number.isFinite(leftTime) !== Number.isFinite(rightTime)) return Number.isFinite(leftTime) ? -1 : 1;
      return left.index - right.index;
    });
}

function phaseStageKey(entry: TimelineEntry): string {
  const phase = entry.metadata?.progress_phase || 'execution';
  const operation = entry.metadata?.progress_step || entry.summary || entry.content || phase;
  return `phase:${phase}:${operation}`;
}

function toolStageKey(entry: TimelineEntry): string {
  return `tool:${entry.correlation_id || entry.step_id || entry.id || entry.timestamp}`;
}

function artifactStageKey(entry: TimelineEntry): string {
  const artifact = entry.artifact;
  return `artifact:${artifact?.artifactId || entry.id || entry.timestamp}`;
}

function mergeStage(existing: AgentRunStage, update: AgentRunStage): AgentRunStage {
  const state = update.state === 'active' && existing.state !== 'active' ? existing.state : update.state;
  return {
    ...existing,
    label: existing.label || update.label,
    state,
    completedAt: state === 'completed' || state === 'failed' ? update.startedAt : existing.completedAt,
    artifactId: existing.artifactId || update.artifactId,
  };
}

function isPartialOutcome(outcome: string | undefined): boolean {
  const normalizedOutcome = outcome?.trim().toLowerCase();
  return normalizedOutcome === 'partial';
}

function terminalState(status: string, outcome: string | undefined): AgentRunPresentation['terminalState'] {
  if (isPartialOutcome(outcome) || status === 'partial') return 'completed';
  if (status === 'failed') return 'failed';
  if (status === 'completed') return 'completed';
  return 'active';
}

export function deriveAgentRunPresentation(
  timeline: TimelineEntry[],
  taskStatus: string,
  isProcessing: boolean,
  taskOutcome?: string,
): AgentRunPresentation {
  const stages: AgentRunStage[] = [];
  const indexesById = new Map<string, number>();
  let finalSummary: TimelineEntry | undefined;

  const appendOrMerge = (stage: AgentRunStage) => {
    const index = indexesById.get(stage.id);
    if (index === undefined) {
      indexesById.set(stage.id, stages.length);
      stages.push(stage);
      return;
    }
    stages[index] = mergeStage(stages[index], stage);
  };

  for (const { entry } of stableChronologicalEntries(timeline)) {
    if (entry.detail_kind === 'final_summary') {
      finalSummary = entry;
      continue;
    }

    const phase = entry.metadata?.progress_phase;
    if (typeof phase === 'string' && phase.trim()) {
      appendOrMerge({
        id: phaseStageKey(entry),
        kind: 'phase',
        label: userFacingLabel(entry, phase),
        state: stageState(timelineStatus(entry), 'recorded'),
        startedAt: entry.timestamp,
        phase: phase.trim(),
      });
      continue;
    }

    const isToolStart = entry.detail_kind === 'tool_input' || entry.type === 'tool_start';
    const isToolResult = entry.detail_kind === 'tool_result' || entry.type === 'tool_complete';
    if (isToolStart || isToolResult) {
      appendOrMerge({
        id: toolStageKey(entry),
        kind: 'tool',
        label: userFacingLabel(entry, 'Tool work'),
        state: stageState(timelineStatus(entry), isToolResult ? 'completed' : 'active'),
        startedAt: entry.timestamp,
      });
      continue;
    }

    if (entry.detail_kind === 'artifact') {
      appendOrMerge({
        id: artifactStageKey(entry),
        kind: 'artifact',
        label: entry.artifact?.displayName || userFacingLabel(entry, 'Created document'),
        state: entry.artifact?.lifecycle === 'unavailable' ? 'recorded' : 'completed',
        startedAt: entry.timestamp,
        completedAt: entry.timestamp,
        artifactId: entry.artifact?.artifactId,
      });
    }
  }

  const resolvedTerminalState = terminalState(taskStatus, taskOutcome);
  const hasPartialOutcome = isPartialOutcome(taskOutcome) || taskStatus === 'partial';
  const normalizedStages = stages.map(stage => {
    if (isProcessing || resolvedTerminalState !== 'completed' || stage.state !== 'active') return stage;
    if (stage.kind === 'phase') return { ...stage, state: 'completed' as const, completedAt: stage.completedAt || stage.startedAt };
    if (stage.kind === 'tool') return { ...stage, state: 'recorded' as const };
    return stage;
  });

  if (finalSummary || resolvedTerminalState !== 'active') {
    normalizedStages.push({
      id: `outcome:${finalSummary?.id || resolvedTerminalState}`,
      kind: 'outcome',
      label: finalSummary
        ? userFacingLabel(finalSummary, 'Final result')
        : hasPartialOutcome
          ? 'Partial result'
          : resolvedTerminalState === 'failed'
            ? 'Run failed'
            : 'Run completed',
      state: resolvedTerminalState === 'failed' ? 'failed' : resolvedTerminalState === 'completed' ? 'completed' : 'active',
      startedAt: finalSummary?.timestamp || normalizedStages[normalizedStages.length - 1]?.startedAt || '',
      completedAt: resolvedTerminalState === 'active' ? undefined : finalSummary?.timestamp || normalizedStages[normalizedStages.length - 1]?.startedAt || '',
    });
  }

  return { stages: normalizedStages, terminalState: resolvedTerminalState };
}

export interface AgentRunOverviewStage {
  id: string;
  kind: 'phase' | 'outcome';
  label: string;
  state: AgentRunStageState;
  startedAt: string;
  completedAt?: string;
  artifactCount: number;
}

export interface AgentRunOverviewPresentation {
  stages: AgentRunOverviewStage[];
  activityCount: number;
  artifactCount: number;
  terminalState: AgentRunPresentation['terminalState'];
}

const OVERVIEW_PHASES: Record<string, { key: string; label: string }> = {
  routing: { key: 'setup', label: 'Preparing request' },
  provider: { key: 'setup', label: 'Preparing request' },
  analysis: { key: 'preparation', label: 'Preparing approach' },
  planning: { key: 'preparation', label: 'Preparing approach' },
  tool_setup: { key: 'preparation', label: 'Preparing approach' },
  skill_selection: { key: 'preparation', label: 'Preparing approach' },
  staged_tool_loading: { key: 'preparation', label: 'Preparing approach' },
  execution: { key: 'execution', label: 'Completing task' },
  finalization: { key: 'execution', label: 'Completing task' },
};

function overviewPhaseKey(stage: AgentRunStage): string {
  const phase = (stage.phase || '').trim().toLocaleLowerCase();
  return OVERVIEW_PHASES[phase]?.key || 'execution';
}

function overviewPhaseLabel(stage: AgentRunStage): string {
  const phase = (stage.phase || '').trim().toLocaleLowerCase();
  return OVERVIEW_PHASES[phase]?.label || 'Completing task';
}

function mergeOverviewPhase(
  existing: AgentRunOverviewStage,
  stage: AgentRunStage,
): AgentRunOverviewStage {
  return {
    ...existing,
    state: stage.state,
    completedAt: stage.completedAt || existing.completedAt,
  };
}

export function deriveAgentRunOverviewPresentation(
  presentation: AgentRunPresentation,
): AgentRunOverviewPresentation {
  const stages: AgentRunOverviewStage[] = [];
  const phaseIndexes = new Map<string, number>();
  let latestPhaseIndex: number | undefined;
  let artifactCount = 0;
  let outcome: AgentRunStage | undefined;

  for (const stage of presentation.stages) {
    if (stage.kind === 'phase') {
      const key = overviewPhaseKey(stage);
      const existingIndex = phaseIndexes.get(key);
      if (existingIndex === undefined) {
        phaseIndexes.set(key, stages.length);
        latestPhaseIndex = stages.length;
        stages.push({
          id: `overview:${key}`,
          kind: 'phase',
          label: overviewPhaseLabel(stage),
          state: stage.state,
          startedAt: stage.startedAt,
          completedAt: stage.completedAt,
          artifactCount: 0,
        });
      } else {
        latestPhaseIndex = existingIndex;
        stages[existingIndex] = mergeOverviewPhase(stages[existingIndex], stage);
      }
      continue;
    }

    if (stage.kind === 'artifact') {
      artifactCount += 1;
      if (latestPhaseIndex !== undefined) {
        stages[latestPhaseIndex] = {
          ...stages[latestPhaseIndex],
          artifactCount: stages[latestPhaseIndex].artifactCount + 1,
        };
      }
      continue;
    }

    if (stage.kind === 'outcome') outcome = stage;
  }

  const firstNonOutcomeStage = presentation.stages.find(stage => stage.kind !== 'outcome');
  if (stages.length === 0 && firstNonOutcomeStage) {
    stages.push({
      id: 'overview:activity',
      kind: 'phase',
      label: 'Run activity',
      state: firstNonOutcomeStage.state,
      startedAt: firstNonOutcomeStage.startedAt,
      completedAt: firstNonOutcomeStage.completedAt,
      artifactCount,
    });
  }

  if (outcome || presentation.terminalState !== 'active') {
    const terminalOutcome = outcome || {
      id: `outcome:${presentation.terminalState}`,
      kind: 'outcome' as const,
      label: presentation.terminalState === 'failed' ? 'Run failed' : 'Run completed',
      state: presentation.terminalState === 'failed' ? 'failed' as const : 'completed' as const,
      startedAt: stages[stages.length - 1]?.startedAt || '',
      completedAt: stages[stages.length - 1]?.completedAt,
    };
    stages.push({
      id: `overview:${terminalOutcome.id}`,
      kind: 'outcome',
      label: terminalOutcome.label,
      state: terminalOutcome.state,
      startedAt: terminalOutcome.startedAt,
      completedAt: terminalOutcome.completedAt,
      artifactCount: 0,
    });
  }

  const lastPhaseIndex = stages.reduce<number | undefined>(
    (latestIndex, stage, index) => stage.kind === 'phase' ? index : latestIndex,
    undefined,
  );
  const normalizedStages = stages.map((stage, index) => {
    if (stage.kind !== 'phase') return stage;
    if (presentation.terminalState === 'completed') {
      return { ...stage, state: 'completed' as const, completedAt: stage.completedAt || stage.startedAt };
    }
    if (stage.state === 'failed' || stage.state === 'waiting') return stage;
    if (presentation.terminalState === 'active' && index < (lastPhaseIndex ?? 0)) {
      return { ...stage, state: 'completed' as const, completedAt: stage.completedAt || stage.startedAt };
    }
    return stage;
  });

  return {
    stages: normalizedStages,
    activityCount: presentation.stages.length,
    artifactCount,
    terminalState: presentation.terminalState,
  };
}
