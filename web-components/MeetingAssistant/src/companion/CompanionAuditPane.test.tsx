import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
import { EMPTY_COMPANION_STATUS, type CompanionGlobalSettings } from './types';

const ui = {
  localAnalysisModels: [],
  apiAnalysisModels: [],
  useApiModelsForAnalysis: false,
  selectedAnalysisModelId: 'model-a',
  isAnalyzing: false,
  isLoadingAnalysisModels: false,
  companionApiPort: 0,
} as unknown as MeetingUIStateDTO;

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

const moment = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  start: 65,
  end: 80,
  kind: 'todo' as const,
  why: 'Nobody took the vendor follow-up.',
  suggested_text: 'Email Acme about the renewal term this week.',
  confidence: 0.8,
  mark: null,
  ...overrides,
});

const audit = (moments = [moment('am-1')], overrides: Record<string, unknown> = {}) => ({
  audit_id: 'au-1',
  scope: 'meeting' as const,
  summary: 'Mostly right to stay quiet.',
  moments,
  evaluations: 6,
  spoke: 2,
  covered_until: 120,
  ...overrides,
});

function withAudit(value: ReturnType<typeof audit> | null, extra: Partial<typeof emptyTimelineState> = {}, state: Partial<CompanionStoreState> = {}) {
  return makeController({ ...withTimeline({ evaluationTotal: 6, audit: value, ...extra }), ...state });
}

function openAudit() {
  fireEvent.click(screen.getByRole('button', { name: /^Audit/ , expanded: false }));
}

describe('CompanionPane audit', () => {
  it('offers Audit so far while recording and Audit this meeting afterwards', () => {
    renderPane(withAudit(null));
    expect(screen.getByRole('button', { name: 'Audit so far' })).toBeInTheDocument();
  });

  it('offers Audit this meeting for a finished meeting and starts the audit', async () => {
    const controller = withAudit(null, {}, { status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } });
    renderPane(controller, false);
    fireEvent.click(screen.getByRole('button', { name: 'Audit this meeting' }));
    expect(controller.runAudit).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText(/An audit reads the transcript|Reviewing/)).toBeInTheDocument());
  });

  it('hides the section until the Companion has checked at least once or an audit exists', () => {
    renderPane(makeController(withTimeline({ evaluationTotal: 0, audit: null })));
    expect(screen.queryByRole('button', { name: 'Audit so far' })).toBeNull();
    renderPane(withAudit(audit()));
    expect(screen.getByRole('button', { name: 'Audit: 1 finding' })).toBeInTheDocument();
  });

  it('shows the counts, the summary and each finding with its actions', () => {
    renderPane(withAudit(audit([moment('am-1'), moment('am-2', { kind: 'research', suggested_text: 'Look up the security audit findings.' })])));
    openAudit();
    expect(screen.getByText('Checked 6 times, spoke 2, 2 possible misses')).toBeInTheDocument();
    expect(screen.getByText('Mostly right to stay quiet.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Make to-do' }).length).toBe(2);
    expect(screen.getAllByRole('button', { name: 'Hand to agent' }).length).toBe(2);
    expect(screen.getAllByRole('button', { name: 'Investigate' }).length).toBe(2);
  });

  it('puts every finding action and both verdicts in one icon row with explanatory tooltips', () => {
    renderPane(withAudit(audit([moment('am-1', { mark: 'disagree' })])));
    openAudit();
    const row = screen.getByRole('button', { name: 'Make to-do' }).closest('.companion-item-actions');
    expect(row).not.toBeNull();
    for (const name of ['Make to-do', 'Hand to agent', 'Investigate', 'Good catch', 'Not needed']) {
      const button = screen.getByRole('button', { name });
      expect(button.closest('.companion-item-actions')).toBe(row);
      expect(button.textContent).toBe('');
      expect(button.getAttribute('title')).toContain(name);
    }
    expect(screen.getByRole('button', { name: 'Good catch' })).toHaveAttribute('title', 'Good catch: the Companion should have said this');
    expect(screen.getByRole('button', { name: 'Not needed' })).toHaveAttribute('aria-pressed', 'true');
    const end = screen.getByRole('button', { name: 'Make to-do' }).closest('.companion-item-actions-end');
    expect(screen.getByRole('button', { name: 'Hand to agent' }).closest('.companion-item-actions-end')).toBe(end);
    for (const name of ['Investigate', 'Good catch', 'Not needed']) {
      expect(screen.getByRole('button', { name }).closest('.companion-item-actions-end')).toBeNull();
    }
  });

  it('says plainly when nothing was missed', () => {
    renderPane(withAudit(audit([])));
    fireEvent.click(screen.getByRole('button', { name: 'Audit: 0 findings' }));
    expect(screen.getByText('Checked 6 times, spoke 2, no missed moments found')).toBeInTheDocument();
  });

  it('turns a finding into a to-do or an agent task and investigates it after the meeting', async () => {
    const controller = withAudit(audit(), {}, { status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } });
    renderPane(controller, false);
    openAudit();
    fireEvent.click(screen.getByRole('button', { name: 'Make to-do' }));
    expect(controller.actOnItem).toHaveBeenCalledWith('am-1', 'todo');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Hand to agent' })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: 'Hand to agent' }));
    expect(controller.actOnItem).toHaveBeenCalledWith('am-1', 'agent_task');
    fireEvent.click(screen.getByRole('button', { name: 'Investigate' }));
    expect(controller.investigate).toHaveBeenCalledWith('Email Acme about the renewal term this week.');
  });

  it('records agree and disagree marks, and clicking the same mark again clears it', () => {
    const controller = withAudit(audit([moment('am-1', { mark: 'agree' })]));
    renderPane(controller);
    openAudit();
    expect(screen.getByRole('button', { name: 'Good catch' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Good catch' }));
    expect(controller.sendFeedback).toHaveBeenCalledWith('am-1', 'audit_clear');
    fireEvent.click(screen.getByRole('button', { name: 'Not needed' }));
    expect(controller.sendFeedback).toHaveBeenCalledWith('am-1', 'audit_disagree');
  });

  it('replaces the action buttons with the outcome once a finding has an action card', () => {
    const card = {
      id: 'p9',
      seq: 0,
      kind: 'proposal' as const,
      text: 'Email Acme about the renewal term this week.',
      confidence: 0.8,
      citations: [],
      no_source: false,
      transcript_range: { start: 65, end: 80, turn_ids: [] },
      trigger: 'item_action',
      watch_id: null,
      truncated: false,
      pinned: false,
      dismissed: false,
      source_item_id: 'am-1',
      proposal: { proposal_id: 'pr-1', action: 'todo' as const, title: 'Email Acme', instruction: 'Email Acme', authority: 'review' as const, state: 'started' as const, todo_id: 't1', agent_task_id: null, error: null, auto_started: false },
    };
    renderPane(withAudit(audit(), { items: [card] }));
    openAudit();
    expect(screen.queryByRole('button', { name: 'Make to-do' })).toBeNull();
    expect(screen.getAllByText('Added to your To-Do list.').length).toBeGreaterThan(0);
  });

  it('shows the audit running and disables the button while it does', () => {
    const controller = withAudit(null, {}, { status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, auditing: true } });
    renderPane(controller);
    expect(screen.getByRole('button', { name: 'Auditing…' })).toBeDisabled();
  });

  it('says so when an audit ends without a report', async () => {
    const running = { status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, auditing: true } };
    const idle = { status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true } };
    const first = withAudit(null, {}, idle);
    const view = renderPane(first);
    fireEvent.click(screen.getByRole('button', { name: 'Audit so far' }));
    await act(async () => undefined);
    const failure = { code: 'audit_failed', message: 'The audit failed: timeout' };
    const makePane = (controller: CompanionController) => (
      <CompanionPane ui={ui} controller={controller} globalSettings={{ settings: globalSettings, update: vi.fn(async () => true), refresh: vi.fn(async () => undefined) }} isTargetRecording variant="embedded" />
    );
    view.rerender(makePane(withAudit(null, { lastError: failure }, running)));
    view.rerender(makePane(withAudit(null, { lastError: failure }, idle)));
    expect(await screen.findByRole('alert')).toHaveTextContent('The audit failed: timeout');
  });
});
