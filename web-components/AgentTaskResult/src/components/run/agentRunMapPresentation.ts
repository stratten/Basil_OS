import { plainMarkdownText } from '../../../../shared/plainMarkdownText';
import {
  deriveAgentRunOverviewPresentation,
  deriveAgentRunPresentation,
  type AgentRunOverviewPresentation,
} from './agentRunPresentation';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { runControlTone } from '../interaction/userInteractions';

export type RunStatusTone = 'processing' | 'waiting' | 'paused' | 'failed' | 'partial' | 'note' | 'completed';

export interface RunStatusPresentation {
  label: string;
  tone: RunStatusTone;
}

export const RUN_STATUS_TONE_CLASS: Record<RunStatusTone, string> = {
  processing: 'is-processing',
  waiting: 'is-awaitingInput',
  paused: 'is-paused',
  failed: 'is-failed',
  partial: 'is-partial',
  note: 'is-completed',
  completed: 'is-completed',
};

// A run whose direct write verified its artifact but only carries an
// agent-generated "partial" advisory (warning severity) completed its
// requested effect; it must not present with the same red marker as an
// actual execution/verification failure.
export function presentRunStatus(run: AgentTaskRunFocusSummary): RunStatusPresentation {
  if (run.isProcessing || run.taskStatus === 'routing' || run.taskStatus === 'capturing') {
    return { label: 'In progress', tone: 'processing' };
  }
  if (run.taskStatus === 'awaitingInput') {
    return { label: 'Waiting for input', tone: 'waiting' };
  }
  if (run.taskStatus === 'paused') {
    return { label: 'Paused', tone: 'paused' };
  }
  if (run.taskStatus === 'canceled') {
    return { label: 'Stopped', tone: 'failed' };
  }
  const isVerifiedContinuityNote = run.hasVerifiedArtifactOutput
    && run.outcome === 'partial'
    && run.resultSeverity === 'warning';
  if (isVerifiedContinuityNote) {
    return { label: 'Completed with note', tone: 'note' };
  }
  // A partial outcome is never red: the run delivered useful content with a residual gap, whether or not it wrote documents and whether or not those are verified.
  if (run.outcome === 'partial') {
    return { label: 'Partial result', tone: 'partial' };
  }
  if (run.taskStatus === 'failed') {
    return { label: 'Needs attention', tone: 'failed' };
  }
  return { label: 'Completed', tone: 'completed' };
}

export type RunAttentionKind = 'failed' | 'waiting' | 'paused' | 'partial' | 'note';

export interface RunAttention {
  kind: RunAttentionKind;
  label: string;
}

export function runAttention(
  run: AgentTaskRunFocusSummary,
  overview: AgentRunOverviewPresentation,
): RunAttention | null {
  // A run the user stopped is already explained by its status dot and run card, so it gets no attention badge.
  if (run.taskStatus === 'canceled') return null;
  const status = presentRunStatus(run);
  if (status.tone === 'failed') return { kind: 'failed', label: 'Needs attention' };
  const hasUnansweredExchange = overview.stages.some(
    stage => stage.kind === 'interaction' && stage.state === 'waiting' && !runControlTone(stage.interaction),
  );
  if (status.tone === 'paused') return { kind: 'paused', label: 'Paused' };
  if (status.tone === 'waiting' || hasUnansweredExchange) return { kind: 'waiting', label: 'Waiting for you' };
  if (status.tone === 'partial') return { kind: 'partial', label: 'Partial result' };
  if (status.tone === 'note') return { kind: 'note', label: 'Note' };
  return null;
}

export function deriveRunOverview(run: AgentTaskRunFocusSummary): AgentRunOverviewPresentation {
  return deriveAgentRunOverviewPresentation(deriveAgentRunPresentation(
    run.executionTimeline,
    run.taskStatus,
    run.isProcessing,
    run.outcome,
  ));
}

export function documentCountLabel(count: number): string | null {
  if (count <= 0) return null;
  return count === 1 ? '1 doc' : `${count} docs`;
}

export interface AgentRunMapTurn {
  run: AgentTaskRunFocusSummary;
  overview: AgentRunOverviewPresentation;
  status: RunStatusPresentation;
  attention: RunAttention | null;
  requestText: string;
  documentLabel: string | null;
}

export function deriveAgentRunMapTurns(runs: AgentTaskRunFocusSummary[]): AgentRunMapTurn[] {
  return runs.map(run => {
    const overview = deriveRunOverview(run);
    return {
      run,
      overview,
      status: presentRunStatus(run),
      attention: runAttention(run, overview),
      requestText: plainMarkdownText(run.requestText),
      documentLabel: documentCountLabel(run.documentCount),
    };
  });
}
