// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TimelineEntry } from '../../types';
import { AgentRunMap } from './AgentRunMap';
import { deriveRunOverview } from './agentRunMapPresentation';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { EMPTY_RUN_ARTIFACTS } from './RunCard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const rootRun: AgentTaskRunFocusSummary = {
  id: 'root',
  kind: 'root',
  ordinal: 1,
  label: 'Initial request',
  requestText: 'Investigate the **integration** workflow',
  resultText: 'The integration workflow failed.',
  timestamp: '2026-08-10T12:00:00Z',
  taskStatus: 'failed',
  outcome: 'failed',
  isProcessing: false,
  documentCount: 1,
  structuredFiles: [],
  executionTimeline: [],
};

const followUpRun: AgentTaskRunFocusSummary = {
  id: 'follow-up',
  kind: 'follow_up',
  ordinal: 2,
  label: 'Follow-up 1',
  requestText: 'Retry with the fallback provider',
  resultText: '',
  timestamp: '2026-08-10T12:01:00Z',
  taskStatus: 'processing',
  isProcessing: true,
  documentCount: 0,
  structuredFiles: [],
  executionTimeline: [],
};

const interactionTimeline: TimelineEntry[] = [
  { id: 'exec-1', type: 'step', timestamp: '2026-10-04T23:39:00Z', content: 'Searching', metadata: { progress_phase: 'execution' } },
  {
    id: 'user_interaction_cp',
    type: 'step',
    timestamp: '2026-10-04T23:40:02Z',
    content: 'Which hotel?',
    detail_kind: 'user_interaction',
    metadata: {
      progress_step: 'You answered',
      user_interaction: { interaction_id: 'cp', kind: 'clarification', status: 'answered', prompt: 'Which hotel?', asked_at: '2026-10-04T23:40:02Z', response: 'La Fantaisie' },
    },
  },
];

const handlers = {
  onPreviewArtifact: vi.fn(),
  onNavigateRun: vi.fn(),
  onTogglePeekRun: vi.fn(),
  onOpenRunDocuments: vi.fn(),
  onJumpToLatestRun: vi.fn(),
};

let container: HTMLDivElement | undefined;
let root: Root | undefined;

function renderMap(overrides: {
  runs?: AgentTaskRunFocusSummary[];
  locationRunId?: string;
  focusedRunId?: string;
  peekedRunIds?: string[];
} = {}) {
  const runs = overrides.runs ?? [rootRun, followUpRun];
  const focusedRunId = overrides.focusedRunId ?? 'follow-up';
  const focusedRun = runs.find(run => run.id === focusedRunId) ?? runs[runs.length - 1];
  if (!container) {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  }
  act(() => {
    root?.render(
      <AgentRunMap
        runs={runs}
        focusedRunId={focusedRunId}
        locationRunId={overrides.locationRunId ?? 'follow-up'}
        currentRunId="follow-up"
        peekedRunIds={overrides.peekedRunIds ?? []}
        focusedPresentation={deriveRunOverview(focusedRun)}
        focusedIsProcessing={focusedRun.isProcessing}
        artifacts={EMPTY_RUN_ARTIFACTS}
        {...handlers}
      />,
    );
  });
  return container;
}

function turnFor(label: string): HTMLElement | undefined {
  return Array.from(container?.querySelectorAll<HTMLElement>('.agent-run-map-turn') ?? [])
    .find(turn => turn.querySelector('.agent-run-map-label')?.textContent === label);
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
  container = undefined;
  root = undefined;
  Object.values(handlers).forEach(handler => handler.mockClear());
});

describe('AgentRunMap', () => {
  it('lists every turn and expands only the location turn', () => {
    const view = renderMap();
    expect(view.querySelector('.agent-run-map-title')?.textContent).toBe('Task map · 2 turns');
    expect(view.querySelectorAll('.agent-run-map-turn')).toHaveLength(2);
    expect(view.querySelectorAll('.agent-run-map-turn.is-expanded')).toHaveLength(1);
    expect(turnFor('Follow-up 1')?.classList.contains('is-expanded')).toBe(true);
    expect(turnFor('Follow-up 1')?.querySelector('.agent-run-map-turn-link')?.getAttribute('aria-current')).toBe('location');
    expect(turnFor('Follow-up 1')?.querySelector('button.agent-run-map-turn-toggle')).toBeNull();
    expect(turnFor('Initial request')?.querySelector('.agent-run-map-turn-link')?.hasAttribute('aria-current')).toBe(false);
    expect(turnFor('Initial request')?.querySelector('.agent-run-map-request')?.textContent).toBe('Investigate the integration workflow');
    expect(view.querySelectorAll('.run-card')).toHaveLength(1);
  });

  it('navigates to a turn when its header is clicked', () => {
    renderMap();
    act(() => {
      turnFor('Initial request')?.querySelector<HTMLButtonElement>('.agent-run-map-turn-link')?.click();
    });
    expect(handlers.onNavigateRun).toHaveBeenCalledWith('root', { kind: 'run' });
  });

  it('peeks a prior turn without navigating, then navigates from one of its stages', () => {
    renderMap();
    const toggle = turnFor('Initial request')?.querySelector<HTMLButtonElement>('button.agent-run-map-turn-toggle');
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    act(() => {
      toggle?.click();
    });
    expect(handlers.onTogglePeekRun).toHaveBeenCalledWith('root');
    expect(handlers.onNavigateRun).not.toHaveBeenCalled();

    renderMap({ peekedRunIds: ['root'] });
    const peekedTurn = turnFor('Initial request');
    expect(peekedTurn?.classList.contains('is-expanded')).toBe(true);
    expect(peekedTurn?.querySelector('button.agent-run-map-turn-toggle')?.getAttribute('aria-expanded')).toBe('true');
    expect(container?.querySelectorAll('.run-card')).toHaveLength(2);
    act(() => {
      peekedTurn?.querySelector<HTMLButtonElement>('.run-card-stage--outcome')?.click();
    });
    expect(handlers.onNavigateRun).toHaveBeenCalledWith('root', { kind: 'section', section: 'result' });
  });

  it('shows attention badges only on collapsed turns', () => {
    renderMap();
    expect(turnFor('Initial request')?.querySelector('.agent-run-map-attention.is-failed')?.textContent).toBe('Needs attention');
    renderMap({ peekedRunIds: ['root'] });
    expect(turnFor('Initial request')?.querySelector('.agent-run-map-attention')).toBeNull();
  });

  it('opens a turn’s documents from its document count', () => {
    renderMap();
    const chip = turnFor('Initial request')?.querySelector<HTMLButtonElement>('.agent-run-map-documents');
    expect(chip?.textContent).toBe('1 doc');
    expect(chip?.getAttribute('aria-label')).toBe('Open 1 doc from Initial request');
    expect(turnFor('Follow-up 1')?.querySelector('.agent-run-map-documents')).toBeNull();
    act(() => {
      chip?.click();
    });
    expect(handlers.onOpenRunDocuments).toHaveBeenCalledWith('root');
  });

  it('offers Jump to latest only while reading an earlier turn of a running task', () => {
    const atLatest = renderMap();
    expect(atLatest.querySelector('.agent-run-map-jump')).toBeNull();

    const readingEarlier = renderMap({ locationRunId: 'root', focusedRunId: 'root' });
    const jump = readingEarlier.querySelector<HTMLButtonElement>('.agent-run-map-jump');
    expect(jump?.textContent).toBe('Jump to latest');
    act(() => {
      jump?.click();
    });
    expect(handlers.onJumpToLatestRun).toHaveBeenCalledTimes(1);

    const finished = renderMap({
      runs: [rootRun, { ...followUpRun, taskStatus: 'completed', isProcessing: false }],
      locationRunId: 'root',
      focusedRunId: 'root',
    });
    expect(finished.querySelector('.agent-run-map-jump')).toBeNull();
  });

  it('navigates to the exchange when an interaction stage is clicked', () => {
    renderMap({
      runs: [{ ...rootRun, taskStatus: 'completed', outcome: 'completed', executionTimeline: interactionTimeline }, followUpRun],
      peekedRunIds: ['root'],
    });
    act(() => {
      turnFor('Initial request')?.querySelector<HTMLButtonElement>('.run-card-stage--interaction')?.click();
    });
    expect(handlers.onNavigateRun).toHaveBeenCalledWith('root', { kind: 'interaction', entryId: 'user_interaction_cp' });
  });
});
