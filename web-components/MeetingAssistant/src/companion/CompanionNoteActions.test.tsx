import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
import { emptyTimelineState, parseCompanionItem } from './companionReducer';
import { initialCompanionStoreState, type CompanionStoreState } from './companionStore';
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

function makeController(state: Partial<CompanionStoreState> = {}, extras: Partial<CompanionController> = {}): CompanionController {
  const full: CompanionStoreState = {
    ...initialCompanionStoreState,
    phase: 'ready',
    status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true },
    ...state,
  };
  return {
    state: full,
    isLive: full.status.live,
    isEnabled: full.status.live && full.status.enabled,
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
    ...extras,
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

function renderPane(controller: CompanionController, isTargetRecording = true, capabilities: CompanionGlobalSettings['proposal_capabilities'] = globalSettings.proposal_capabilities) {
  return render(
    <CompanionPane ui={ui} controller={controller} globalSettings={{ settings: { ...globalSettings, proposal_capabilities: capabilities }, update: vi.fn(async () => true), refresh: vi.fn(async () => undefined) }} isTargetRecording={isTargetRecording} variant="embedded" />,
  );
}

function withTimeline(timeline: Partial<typeof emptyTimelineState>): Partial<CompanionStoreState> {
  return { timeline: { ...emptyTimelineState, ...timeline } };
}

beforeEach(() => {
  vi.clearAllMocks();
});

const started = {
  proposal_id: 'pr-1',
  action: 'todo' as const,
  title: 'Nobody owns the vendor follow-up.',
  instruction: 'Nobody owns the vendor follow-up.',
  authority: 'review' as const,
  state: 'started' as const,
  todo_id: 'todo-1',
  agent_task_id: null,
  error: null,
  auto_started: false,
};

describe('CompanionPane note actions', () => {
  const note = item('n1', 'Nobody owns the vendor follow-up.', 10, { kind: 'suggestion' });

  it('makes a to-do from a note through the controller', async () => {
    const controller = makeController(withTimeline({ items: [note] }));
    renderPane(controller);
    fireEvent.click(screen.getByRole('button', { name: 'Make to-do' }));
    expect(controller.actOnItem).toHaveBeenCalledWith('n1', 'todo');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Make to-do' })).not.toBeDisabled());
  });

  it('shows the actions as icon buttons in the same row as pin and copy, each with a tooltip that explains it', () => {
    renderPane(makeController(withTimeline({ items: [note] })));
    const row = screen.getByRole('button', { name: 'Pin' }).closest('.companion-item-actions');
    for (const [name, tooltip] of [
      ['Make to-do', 'Make to-do: Add this to your To-Do list'],
      ['Hand to agent', 'Hand to agent: Send this to an agent as a task'],
      ['Investigate', 'Investigate: look this up in your sources'],
    ] as const) {
      const button = screen.getByRole('button', { name });
      expect(button.closest('.companion-item-actions')).toBe(row);
      expect(button).toHaveAttribute('title', tooltip);
      expect(button.textContent).toBe('');
      expect(button.querySelector('svg')).not.toBeNull();
    }
  });

  it('sets Make to-do and Hand to agent apart at the right end of the row and puts Dismiss at the top right of the card', () => {
    renderPane(makeController(withTimeline({ items: [note] })));
    const end = screen.getByRole('button', { name: 'Make to-do' }).closest('.companion-item-actions-end');
    expect(end).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Hand to agent' }).closest('.companion-item-actions-end')).toBe(end);
    for (const name of ['Pin', 'Copy', 'Helpful', 'Not helpful', 'Investigate']) {
      expect(screen.getByRole('button', { name }).closest('.companion-item-actions-end')).toBeNull();
    }
    const dismiss = screen.getByRole('button', { name: 'Dismiss' });
    expect(dismiss.closest('.companion-item-header')).not.toBeNull();
    expect(dismiss.closest('.companion-item-actions')).toBeNull();
  });

  it('hands a note to an agent through the controller', () => {
    const controller = makeController(withTimeline({ items: [note] }));
    renderPane(controller);
    fireEvent.click(screen.getByRole('button', { name: 'Hand to agent' }));
    expect(controller.actOnItem).toHaveBeenCalledWith('n1', 'agent_task');
  });

  it('keeps the buttons on a note in a finished meeting', () => {
    const controller = makeController({ ...withTimeline({ items: [note] }), status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } });
    renderPane(controller, false);
    expect(screen.getByRole('button', { name: 'Make to-do' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hand to agent' })).toBeInTheDocument();
  });

  it('offers only the actions the capability settings allow', () => {
    renderPane(makeController(withTimeline({ items: [note] })), true, ['todo']);
    expect(screen.getByRole('button', { name: 'Make to-do' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Hand to agent' })).toBeNull();
  });

  it('hides both buttons when neither action is allowed', () => {
    renderPane(makeController(withTimeline({ items: [note] })), true, ['assistant_session']);
    expect(screen.queryByRole('button', { name: 'Make to-do' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hand to agent' })).toBeNull();
  });

  it('replaces the buttons with the outcome once the note has an action card', () => {
    const card = item('p9', 'Nobody owns the vendor follow-up.', 10, { kind: 'proposal', source_item_id: 'n1', proposal: started });
    renderPane(makeController(withTimeline({ items: [note, card] })));
    expect(screen.queryByRole('button', { name: 'Make to-do' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hand to agent' })).toBeNull();
    expect(screen.getAllByText('Added to your To-Do list.').length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Proposed To-Do/)).toBeInTheDocument();
    expect(screen.getByText('To-Do from a note')).toBeInTheDocument();
  });

  it('offers the buttons again after the action card was dismissed', () => {
    const card = item('p9', 'Nobody owns the vendor follow-up.', 10, { kind: 'proposal', source_item_id: 'n1', dismissed: true, proposal: { ...started, state: 'dismissed' } });
    renderPane(makeController(withTimeline({ items: [note, card] })));
    expect(screen.getByRole('button', { name: 'Make to-do' })).toBeInTheDocument();
  });

  it('points a failed action at the retry on its card', () => {
    const card = item('p9', 'Nobody owns the vendor follow-up.', 10, { kind: 'proposal', source_item_id: 'n1', proposal: { ...started, state: 'failed', error: 'Worker not ready' } });
    renderPane(makeController(withTimeline({ items: [note, card] })));
    expect(screen.getByText('The action could not be started. Retry it from the card below.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Make to-do' })).toBeNull();
  });

  it('never offers the note buttons on a proposal card', () => {
    const proposal = item('p1', 'Add a renewal reminder', 12, { kind: 'proposal', proposal: { ...started, state: 'proposed', todo_id: null } });
    renderPane(makeController(withTimeline({ items: [proposal] })));
    expect(screen.queryByRole('button', { name: 'Make to-do' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument();
  });

  it('keeps the source note id when an item is parsed and omits it when empty', () => {
    const raw = { ...note, source_item_id: 'n1' };
    expect(parseCompanionItem(raw)?.source_item_id).toBe('n1');
    expect(parseCompanionItem({ ...note, source_item_id: '' })?.source_item_id).toBeUndefined();
    expect(parseCompanionItem(note)?.source_item_id).toBeUndefined();
  });
});
