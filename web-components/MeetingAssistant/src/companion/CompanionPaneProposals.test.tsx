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

function renderPane(controller: CompanionController, isTargetRecording = true) {
  return render(
    <CompanionPane ui={ui} controller={controller} globalSettings={{ settings: globalSettings, update: vi.fn(async () => true), refresh: vi.fn(async () => undefined) }} isTargetRecording={isTargetRecording} variant="embedded" />,
  );
}

function withTimeline(timeline: Partial<typeof emptyTimelineState>): Partial<CompanionStoreState> {
  return { timeline: { ...emptyTimelineState, ...timeline } };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CompanionPane research', () => {
  it('asks the Companion to investigate a note with the note text as the question', () => {
    const controller = makeController(withTimeline({ items: [item('i1', 'The vendor may raise the price next year.', 10)] }));
    renderPane(controller);
    fireEvent.click(screen.getByRole('button', { name: 'Investigate' }));
    expect(controller.investigate).toHaveBeenCalledWith('The vendor may raise the price next year.');
  });

  it('shows the Researched badge and offers no Investigate action on a researched note', () => {
    const researched = item('i1', 'Answer.', 10, { researched: true, evidence_count: 2 });
    renderPane(makeController(withTimeline({ items: [researched] })));
    expect(screen.queryByRole('button', { name: 'Investigate' })).toBeNull();
    expect(screen.getByText('Researched')).toBeInTheDocument();
  });

  it('hides Investigate when the per-meeting research switch is off', () => {
    const controller = makeController({ ...withTimeline({ items: [item('i1', 'A note.', 10)] }), status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, investigate: false } });
    renderPane(controller);
    expect(screen.queryByRole('button', { name: 'Investigate' })).toBeNull();
    expect(screen.getByLabelText('Research questions in my sources')).not.toBeChecked();
  });

  it('turns the research switch off for this meeting', () => {
    const controller = makeController();
    renderPane(controller);
    fireEvent.click(screen.getByLabelText('Research questions in my sources'));
    expect(controller.setInvestigate).toHaveBeenCalledWith(false);
  });

  it('shows the Investigating status and notice with a Stop action while a run is active', () => {
    const retrieval = { id: 'r1', seq: 1, kind: 'retrieval' as const, meeting_time: 1, wall_time: '', payload: { purpose: 'investigation', investigation_id: 'inv-1', queries: ['renewal date'] } };
    const controller = makeController({ ...withTimeline({ retrievals: [retrieval] }), status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, investigating: 1 } });
    renderPane(controller);
    const notice = screen.getByText('Investigating: renewal date').closest('[role="status"]') as HTMLElement;
    fireEvent.click(within(notice).getByRole('button', { name: 'Stop' }));
    expect(controller.stopInvestigations).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText(/Investigating/).length).toBeGreaterThanOrEqual(2);
  });
});

describe('CompanionPane proposals', () => {
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

  it('shows a proposal as an approvable card and approves through the controller', () => {
    const controller = makeController(withTimeline({ items: [proposal] }));
    renderPane(controller);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(controller.decideProposal).toHaveBeenCalledWith('p1', 'approve');
  });

  it('keeps a saved proposal visible in a finished meeting without a recording', () => {
    const controller = makeController({ ...withTimeline({ items: [proposal] }), status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } });
    renderPane(controller, false);
    expect(screen.getByLabelText(/Proposed To-Do/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Follow-up actions' })).toBeNull();
  });

  it('shows the follow-up settings while recording', () => {
    renderPane(makeController());
    expect(screen.getByRole('heading', { name: 'Follow-up actions' })).toBeInTheDocument();
  });

  it('shows the follow-up settings in the off state before the Companion is turned on', () => {
    const controller = makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false } });
    renderPane(controller);
    expect(screen.getByRole('heading', { name: 'Follow-up actions' })).toBeInTheDocument();
  });
});
