import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

const api = vi.hoisted(() => ({ fetchGlobalSettings: vi.fn(), updateGlobalSettings: vi.fn() }));
vi.mock('./companionApi', () => api);
vi.mock('../bridge/meetingBridge', () => ({
  copyText: vi.fn(),
  openCompanionWindow: vi.fn(),
  pickCompanionFolder: vi.fn(),
  setAnalysisConfiguration: vi.fn(),
  subscribeFilesDropped: vi.fn(() => () => undefined),
}));
vi.mock('../../../shared/ReasoningModelPicker', () => ({ default: () => null }));

import { COMPANION_CONTINUE_PROMPT } from './CompanionChatEntry';
import CompanionPane from './CompanionPane';
import { companionPort } from './companionTarget';
import { useCompanionGlobalSettings } from './useCompanionGlobalSettings';
import { emptyTimelineState } from './companionReducer';
import { initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import type { CompanionController } from './useCompanion';
import { EMPTY_COMPANION_STATUS, type ChatMessage, type CompanionItem } from './types';

const ui = {
  localAnalysisModels: [],
  apiAnalysisModels: [],
  useApiModelsForAnalysis: false,
  selectedAnalysisModelId: 'model-a',
  isAnalyzing: false,
  isLoadingAnalysisModels: false,
  companionApiPort: 8123,
} as unknown as MeetingUIStateDTO;

/** Hosts the pane the way the apps do: one global-settings load, owned above the pane, only while the meeting is being recorded. */
function PaneWithSettings(props: Omit<ComponentProps<typeof CompanionPane>, 'globalSettings'>) {
  const globalSettings = useCompanionGlobalSettings(props.isTargetRecording ? companionPort(props.ui) : 0);
  return <CompanionPane {...props} globalSettings={globalSettings} />;
}

function item(id: string, latency?: number): CompanionItem {
  return {
    id,
    seq: 0,
    kind: 'insight',
    text: `text ${id}`,
    confidence: 0.5,
    citations: [],
    no_source: false,
    transcript_range: { start: 0, end: 2, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...(latency === undefined ? {} : { latency_ms: latency }),
  };
}

function makeController(state: Partial<CompanionStoreState>): CompanionController {
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
  };
}

function message(id: string, role: ChatMessage['role'], text: string, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { id, role, text, meeting_time: 1, truncated: false, status: 'complete', seq: 0, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
  const proposalDefaults = { proposal_mode: 'suggestion_only', proposal_capabilities: ['todo', 'agent_task', 'assistant_session'], auto_execute_capabilities: [] };
  api.fetchGlobalSettings.mockResolvedValue({ auto_enable: false, default_mode: 'active', screen_share_note_dismissed: false, ...proposalDefaults });
  api.updateGlobalSettings.mockResolvedValue({ auto_enable: false, default_mode: 'active', screen_share_note_dismissed: true, ...proposalDefaults });
});

describe('CompanionPane reply-time readout and screen-share note', () => {
  it('shows the rolling reply time once three items carry a measurement', () => {
    const controller = makeController({ timeline: { ...emptyTimelineState, items: [item('a', 2000), item('b', 4000), item('c', 6000)] } });
    render(<PaneWithSettings ui={ui} controller={controller} isTargetRecording variant="embedded" />);
    const label = screen.getByText('Listening');
    expect(label).toHaveAttribute('title', expect.stringContaining('Replies in about 4.0s, slow ones 6.0s'));
    expect(label).toHaveAttribute('title', expect.stringContaining('over the last 3 items'));
    expect(screen.queryByText(/Replies in about/)).toBeNull();
  });

  it('hides the readout with too few measurements', () => {
    const controller = makeController({ timeline: { ...emptyTimelineState, items: [item('a', 2000), item('b', 4000), item('c')] } });
    render(<PaneWithSettings ui={ui} controller={controller} isTargetRecording variant="embedded" />);
    expect(screen.getByText('Listening')).not.toHaveAttribute('title', expect.stringContaining('Replies in about'));
  });

  it('shows the screen-share note only while recording, in both pane variants', async () => {
    const live = render(<PaneWithSettings ui={ui} controller={makeController({})} isTargetRecording variant="embedded" />);
    expect(await screen.findByRole('note')).toBeInTheDocument();
    live.unmount();
    const detached = render(<PaneWithSettings ui={ui} controller={makeController({})} isTargetRecording variant="detached" />);
    expect(await screen.findByRole('note')).toBeInTheDocument();
    detached.unmount();
    const saved = render(
      <PaneWithSettings ui={ui} controller={makeController({ status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } })} isTargetRecording={false} variant="embedded" />,
    );
    await waitFor(() => expect(screen.queryByRole('note')).toBeNull());
    expect(api.fetchGlobalSettings).toHaveBeenCalledTimes(2);
    saved.unmount();
  });
});

describe('CompanionPane title', () => {
  it('shows its own title only when embedded, because the detached window chrome already names it', () => {
    const embedded = render(<PaneWithSettings ui={ui} controller={makeController({})} isTargetRecording variant="embedded" />);
    expect(screen.getByText('Companion', { selector: '.shared-history-sidebar-title' })).toBeInTheDocument();
    embedded.unmount();
    render(<PaneWithSettings ui={ui} controller={makeController({})} isTargetRecording variant="detached" />);
    expect(screen.queryByText('Companion', { selector: '.shared-history-sidebar-title' })).toBeNull();
  });

  it('loads the global settings once for the whole pane, not once per control', async () => {
    render(<PaneWithSettings ui={ui} controller={makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false } })} isTargetRecording variant="embedded" />);
    expect(await screen.findByRole('note')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Turn on for every new meeting' })).toBeInTheDocument();
    expect(api.fetchGlobalSettings).toHaveBeenCalledTimes(1);
  });
});

describe('Companion chat Continue action', () => {
  function renderChat(messages: ChatMessage[], store: Partial<CompanionStoreState> = {}, statusOverrides: Partial<typeof EMPTY_COMPANION_STATUS> = {}) {
    const controller = makeController({
      timeline: { ...emptyTimelineState, chat: messages },
      status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, ...statusOverrides },
      ...store,
    });
    const view = render(<PaneWithSettings ui={ui} controller={controller} isTargetRecording variant="embedded" />);
    return { controller, view };
  }

  const cutShort = [message('u1', 'user', 'Why retries?', { seq: 1 }), message('a1', 'assistant', 'Because the upstream', { truncated: true, seq: 2 })];

  it('offers Continue on the latest truncated answer and sends the fixed instruction', () => {
    const { controller } = renderChat(cutShort);
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(controller.sendChat).toHaveBeenCalledWith(COMPANION_CONTINUE_PROMPT);
    expect(COMPANION_CONTINUE_PROMPT).not.toMatch(/comes up/i);
  });

  it('also offers Continue after an interrupted answer that kept partial text', () => {
    renderChat([message('u1', 'user', 'Why retries?', { seq: 1 }), message('a1', 'assistant', 'Because the upstream', { truncated: true, status: 'error', seq: 2 })]);
    expect(screen.getByText('That answer could not be completed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument();
  });

  it('does not offer Continue when the answer is whole, was already followed up, or chat cannot send', () => {
    const whole = renderChat([message('u1', 'user', 'Q', { seq: 1 }), message('a1', 'assistant', 'Complete answer.', { seq: 2 })]);
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull();
    whole.view.unmount();
    const followed = renderChat([...cutShort, message('u2', 'user', 'Another question', { seq: 3 })]);
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull();
    followed.view.unmount();
    renderChat(cutShort, {}, { enabled: false });
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull();
  });

  it('hides Continue while another answer is streaming or pending', () => {
    const streaming = renderChat(cutShort, { drafts: { a2: 'Working' } });
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull();
    streaming.view.unmount();
    renderChat(cutShort, { pendingAssistantIds: ['a3'] });
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull();
  });

  it('disables the button while the request is in flight', async () => {
    let resolveSend: (accepted: boolean) => void = () => undefined;
    const controller = makeController({ timeline: { ...emptyTimelineState, chat: cutShort } });
    controller.sendChat = vi.fn(() => new Promise<boolean>((resolve) => { resolveSend = resolve; }));
    render(<PaneWithSettings ui={ui} controller={controller} isTargetRecording variant="embedded" />);
    const button = screen.getByRole('button', { name: 'Continue' });
    fireEvent.click(button);
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(controller.sendChat).toHaveBeenCalledTimes(1);
    resolveSend(true);
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
