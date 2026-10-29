import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

vi.mock('../bridge/meetingBridge', () => ({
  copyText: vi.fn(),
  openCompanionWindow: vi.fn(),
  openCompanionAssistantSession: vi.fn(),
  openProposalAgentTask: vi.fn(),
  openProposalTodo: vi.fn(),
  pickCompanionFolder: vi.fn(),
  setAnalysisConfiguration: vi.fn(),
  subscribeFilesDropped: vi.fn(() => () => undefined),
}));

vi.mock('../../../shared/TokenizedSelect', () => ({
  default: ({ value, ariaLabel }: { value: string; ariaLabel: string }) => <button type="button" aria-label={ariaLabel}>{`select ${value}`}</button>,
}));

vi.mock('../../../shared/ReasoningModelPicker', () => ({
  default: ({ ariaLabel }: { ariaLabel?: string }) => <button type="button" aria-label={ariaLabel}>picker</button>,
}));

import CompanionPane from './CompanionPane';
import { emptyTimelineState } from './companionReducer';
import { initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import { getCompanionView, resetCompanionViews } from './companionViewStore';
import type { CompanionController } from './useCompanion';
import { EMPTY_COMPANION_STATUS, type CompanionGlobalSettings, type CompanionItem } from './types';

const ui = {
  localAnalysisModels: [],
  apiAnalysisModels: [],
  useApiModelsForAnalysis: false,
  selectedAnalysisModelId: 'model-a',
  isAnalyzing: false,
  isLoadingAnalysisModels: false,
  companionApiPort: 0,
} as unknown as MeetingUIStateDTO;

function item(id: string, text: string, end: number, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id,
    seq: 0,
    kind: 'insight',
    text,
    confidence: 0.5,
    citations: [],
    no_source: false,
    transcript_range: { start: end - 2, end, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...overrides,
  };
}

function makeController(items: CompanionItem[]): CompanionController {
  const full: CompanionStoreState = {
    ...initialCompanionStoreState,
    phase: 'ready',
    status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true },
    timeline: { ...emptyTimelineState, items },
  };
  return {
    state: full,
    isLive: true,
    isEnabled: true,
    pendingRoots: [],
    actionError: null,
    clearActionError: vi.fn(),
    refresh: vi.fn(async () => undefined),
    enable: vi.fn(async () => true),
    disable: vi.fn(async () => true),
    setMode: vi.fn(async () => true),
    addRoots: vi.fn(async () => undefined),
    removeRoot: vi.fn(async () => true),
    removePendingRoot: vi.fn(),
    sendFeedback: vi.fn(async () => true),
    sendChat: vi.fn(async () => true),
    createWatch: vi.fn(async () => true),
    cancelWatch: vi.fn(async () => true),
    setFocus: vi.fn(async () => true),
    decideProposal: vi.fn(async () => null),
    runAudit: vi.fn(async () => true),
    actOnItem: vi.fn(async () => null),
    investigate: vi.fn(async () => true),
    stopInvestigations: vi.fn(async () => true),
    setInvestigate: vi.fn(async () => true),
  };
}

const globalSettings: CompanionGlobalSettings = {
  auto_enable: false,
  default_mode: 'active',
  next_focus: '',
  screen_share_note_dismissed: true,
  proposal_mode: 'suggestion_only',
  proposal_capabilities: ['todo', 'agent_task', 'assistant_session'],
  auto_execute_capabilities: [],
};

function renderPane(controller: CompanionController) {
  return render(
    <CompanionPane ui={ui} controller={controller} globalSettings={{ settings: globalSettings, update: vi.fn(async () => true), refresh: vi.fn(async () => undefined) }} isTargetRecording variant="embedded" />,
  );
}

function card(label: string): HTMLElement {
  return screen.getAllByRole('article').find((candidate) => candidate.getAttribute('aria-label') === label)!;
}

beforeEach(() => {
  vi.clearAllMocks();
  resetCompanionViews();
});

describe('Companion note collapse', () => {
  const long = '**Renewal risk.** The vendor may raise the price next year, see [the contract](https://example.test/c) for the clause that allows it.';

  it('folds a note to its header and a one-line preview without dismissing it', () => {
    const controller = makeController([item('i1', long, 10, { rationale: 'Because of the clause.', citations: [{ path: '/a/b.md', line_start: 1, line_end: 1, excerpt: 'x' }] })]);
    renderPane(controller);
    const open = card('Insight at [00:08]');
    expect(within(open).getByRole('button', { name: 'Collapse' })).toHaveAttribute('aria-expanded', 'true');
    expect(within(open).getByRole('button', { name: 'Pin' })).toBeInTheDocument();

    fireEvent.click(within(open).getByRole('button', { name: 'Collapse' }));

    const folded = card('Insight at [00:08]');
    expect(within(folded).getByRole('button', { name: 'Expand' })).toHaveAttribute('aria-expanded', 'false');
    expect(folded.querySelector('.companion-item-preview')?.textContent).toBe('Renewal risk. The vendor may raise the price next year, see the contract for the clause that allows it.');
    expect(within(folded).queryByRole('button', { name: 'Pin' })).toBeNull();
    expect(within(folded).queryByText('Why this?')).toBeNull();
    expect(within(folded).queryByText('1 source')).toBeNull();
    expect(within(folded).getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
    expect(controller.sendFeedback).not.toHaveBeenCalled();
  });

  it('expands a folded note again with its content intact', () => {
    renderPane(makeController([item('i1', 'The vendor may raise the price.', 10)]));
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Collapse' }));
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Expand' }));
    const reopened = card('Insight at [00:08]');
    expect(reopened.querySelector('.companion-item-preview')).toBeNull();
    expect(within(reopened).getByRole('button', { name: 'Pin' })).toBeInTheDocument();
    expect(within(reopened).getByText('The vendor may raise the price.')).toBeInTheDocument();
  });

  it('folds only the chosen note and keeps the fold across a remount', () => {
    const controller = makeController([item('i1', 'First note.', 10), item('i2', 'Second note.', 20)]);
    const first = renderPane(controller);
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Collapse' }));
    expect(getCompanionView(null).collapsedItemIds).toEqual(['i1']);
    expect(within(card('Insight at [00:18]')).getByRole('button', { name: 'Collapse' })).toBeInTheDocument();

    first.unmount();
    renderPane(controller);
    expect(within(card('Insight at [00:08]')).getByRole('button', { name: 'Expand' })).toBeInTheDocument();
    expect(within(card('Insight at [00:18]')).getByRole('button', { name: 'Collapse' })).toBeInTheDocument();
  });

  it('opens a folded note when its pinned row is chosen', () => {
    renderPane(makeController([item('i1', 'Pinned note body.', 10, { pinned: true })]));
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Collapse' }));
    expect(getCompanionView(null).collapsedItemIds).toEqual(['i1']);

    fireEvent.click(within(screen.getByRole('region', { name: 'Pinned' })).getByRole('button', { name: /Pinned note body/ }));

    expect(getCompanionView(null).collapsedItemIds).toEqual([]);
    expect(within(card('Insight at [00:08]')).getByRole('button', { name: 'Collapse' })).toBeInTheDocument();
  });

  it('leaves other notes folded when one is opened by its pinned row', () => {
    renderPane(makeController([item('i1', 'Pinned note body.', 10, { pinned: true }), item('i2', 'Other note.', 20)]));
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Collapse' }));
    fireEvent.click(within(card('Insight at [00:18]')).getByRole('button', { name: 'Collapse' }));
    fireEvent.click(within(screen.getByRole('region', { name: 'Pinned' })).getByRole('button', { name: /Pinned note body/ }));
    expect(getCompanionView(null).collapsedItemIds).toEqual(['i2']);
  });

  it('does not offer a fold on a proposal card', () => {
    const proposal = item('p1', 'Add a renewal reminder', 12, {
      kind: 'proposal',
      investigation_id: 'inv-1',
      proposal: {
        proposal_id: 'pr-1',
        action: 'todo',
        title: 'Add a renewal reminder',
        instruction: 'Remind me to renew the contract.',
        authority: 'review',
        state: 'proposed',
        todo_id: null,
        agent_task_id: null,
        error: null,
        auto_started: false,
      },
    });
    renderPane(makeController([proposal]));
    expect(screen.queryByRole('button', { name: 'Collapse' })).toBeNull();
  });
});

describe('Companion researched badge placement', () => {
  const source = { path: '/a/b.md', line_start: 3, line_end: 4, excerpt: 'evidence' };

  it('puts the Researched badge in the sources row, after the sources summary', () => {
    renderPane(makeController([item('i1', 'Answer.', 10, { researched: true, evidence_count: 2, citations: [source] })]));
    const open = card('Insight at [00:08]');
    const row = open.querySelector('.companion-item-evidence')!;
    expect(row.querySelector('.companion-citations')).not.toBeNull();
    expect(row.lastElementChild).toBe(within(row as HTMLElement).getByText('Researched'));
    expect(open.querySelector('.companion-item-header .companion-badge')).toBeNull();
  });

  it('still shows the badge, alone in the row, when a researched note has no sources', () => {
    renderPane(makeController([item('i1', 'Answer.', 10, { researched: true })]));
    const row = card('Insight at [00:08]').querySelector('.companion-item-evidence')!;
    expect(row.children).toHaveLength(1);
    expect(within(row as HTMLElement).getByText('Researched')).toBeInTheDocument();
  });

  it('renders no evidence row for a note with neither sources nor research', () => {
    renderPane(makeController([item('i1', 'Plain note.', 10)]));
    expect(card('Insight at [00:08]').querySelector('.companion-item-evidence')).toBeNull();
  });

  it('hides the badge while the note is folded and brings it back on expand', () => {
    renderPane(makeController([item('i1', 'Answer.', 10, { researched: true, citations: [source] })]));
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Collapse' }));
    expect(screen.queryByText('Researched')).toBeNull();
    fireEvent.click(within(card('Insight at [00:08]')).getByRole('button', { name: 'Expand' }));
    expect(screen.getByText('Researched')).toBeInTheDocument();
  });
});
