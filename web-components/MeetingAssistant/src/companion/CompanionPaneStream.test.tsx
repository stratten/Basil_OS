import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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
vi.mock('../../../shared/ReasoningModelPicker', () => ({ default: () => null }));

import { copyText } from '../bridge/meetingBridge';
import CompanionPane from './CompanionPane';
import { CompanionLinksProvider, type CompanionLinks } from './companionLinks';
import { emptyTimelineState } from './companionReducer';
import { initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import { getCompanionView, resetCompanionViews, updateCompanionView } from './companionViewStore';
import type { CompanionController } from './useCompanion';
import { EMPTY_COMPANION_STATUS, type ChatMessage, type CompanionItem, type CompanionRoot } from './types';

const ui = {
  localAnalysisModels: [],
  apiAnalysisModels: [],
  useApiModelsForAnalysis: false,
  selectedAnalysisModelId: 'model-a',
  isAnalyzing: false,
  isLoadingAnalysisModels: false,
  companionApiPort: 0,
  displayedMeetingWorkOwnerId: 'meeting-1',
} as unknown as MeetingUIStateDTO;

function item(id: string, seq: number, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id,
    seq,
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
    ...overrides,
  };
}

function chat(id: string, seq: number, role: ChatMessage['role'], text: string): ChatMessage {
  return { id, seq, role, text, meeting_time: 1, truncated: false, status: 'complete' };
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

function timeline(partial: Partial<typeof emptyTimelineState>): Partial<CompanionStoreState> {
  return { timeline: { ...emptyTimelineState, ...partial } };
}

function renderPane(controller: CompanionController, isTargetRecording = true) {
  const props = { ui, globalSettings: { settings: null, update: vi.fn(async () => false), refresh: vi.fn(async () => undefined) }, isTargetRecording, variant: 'embedded' as const };
  const view = render(<CompanionPane controller={controller} {...props} />);
  return { view, rerender: (next: CompanionController) => view.rerender(<CompanionPane controller={next} {...props} />) };
}

const root: CompanionRoot = { id: 'r1', path: '/tmp/proj', display_name: 'proj', kind: 'folder', attached_at: 0, detached_at: null };

beforeEach(() => {
  vi.clearAllMocks();
  resetCompanionViews();
  Element.prototype.scrollIntoView = vi.fn();
});

describe('Companion stream', () => {
  it('puts the reader\'s question and the answer in the stream at the point they arrived, among the cards', () => {
    renderPane(
      makeController(
        timeline({
          items: [item('early', 1), item('late', 5)],
          chat: [chat('q', 2, 'user', 'What changed?'), chat('a', 3, 'assistant', 'The retry policy.')],
        }),
      ),
    );
    const log = screen.getByRole('log', { name: 'Companion feed' });
    const text = log.textContent ?? '';
    const positions = ['text early', 'What changed?', 'The retry policy.', 'text late'].map((value) => text.indexOf(value));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it('shows a Thinking row while the evaluator runs and nothing when idle', () => {
    const busy = renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, evaluating: true } }));
    expect(within(screen.getByRole('log')).getByText('Thinking…')).toBeInTheDocument();
    busy.view.unmount();
    renderPane(makeController());
    expect(within(screen.getByRole('log')).queryByText('Thinking…')).toBeNull();
  });

  it('shows no working row for a saved meeting', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false, evaluating: true, investigating: 0 }, ...timeline({ items: [item('a', 1)] }) }), false);
    expect(screen.queryByText('Thinking…')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
  });

  it('lists pinned items in a strip that takes the reader to the full card, and collapses', () => {
    renderPane(makeController(timeline({ items: [item('a', 1), item('b', 2, { pinned: true, text: 'Remember this pricing' })] })));
    const strip = screen.getByRole('region', { name: 'Pinned' });
    expect(within(strip).getByText('Remember this pricing')).toBeInTheDocument();
    fireEvent.click(within(strip).getByRole('button', { name: /Remember this pricing/ }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
    const bravoRow = document.querySelector('[data-stream-key="item:b"]');
    expect(bravoRow).toHaveClass('is-highlighted');

    const toggle = within(strip).getByRole('button', { name: /Pinned \(1\)/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(getCompanionView('meeting-1').pinnedOpen).toBe(false);
  });

  it('has no pinned strip when nothing is pinned, and does not list a dismissed pinned item', () => {
    renderPane(makeController(timeline({ items: [item('a', 1), item('b', 2, { pinned: true, dismissed: true })] })));
    expect(screen.queryByRole('region', { name: 'Pinned' })).toBeNull();
  });

  it('flags a proposal that needs a decision and takes the reader to it', () => {
    const proposal = item('p', 4, {
      kind: 'proposal',
      proposal: { proposal_id: 'pr', action: 'todo', title: 'Send the notes', instruction: 'Send them.', authority: 'review', state: 'proposed', todo_id: null, agent_task_id: null, error: null, auto_started: false },
    });
    renderPane(makeController(timeline({ items: [item('a', 1), proposal] })));
    expect(screen.getAllByText('Needs your decision').length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole('button', { name: 'Needs your decision (1)' }));
    expect(document.querySelector('[data-stream-key="item:p"]')).toHaveClass('is-highlighted');
  });

  it('removes the decision flag once the proposal is decided', () => {
    const decided = item('p', 4, {
      kind: 'proposal',
      proposal: { proposal_id: 'pr', action: 'todo', title: 'Send the notes', instruction: 'Send them.', authority: 'review', state: 'started', todo_id: 't', agent_task_id: null, error: null, auto_started: false },
    });
    renderPane(makeController(timeline({ items: [decided] })));
    expect(screen.queryByText(/Needs your decision/)).toBeNull();
  });
});

describe('Companion settings section and composer', () => {
  it('opens the settings on a first run with nothing attached, and summarizes them once configured', () => {
    const first = renderPane(makeController());
    expect(screen.getByRole('button', { name: /^Companion settings/ })).toHaveAttribute('aria-expanded', 'true');
    first.view.unmount();
    resetCompanionViews();
    renderPane(makeController(timeline({ roots: [root], watches: [{ id: 'w', topic: 'pricing', instruction: '', keywords: [], created_at: 0, active: true, last_triggered_at: null }] })));
    const toggle = screen.getByRole('button', { name: /^Companion settings/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveTextContent('1 source, 1 watch, research on');
  });

  it('remembers that the reader closed or opened the settings across a remount', () => {
    const first = renderPane(makeController());
    fireEvent.click(screen.getByRole('button', { name: /^Companion settings/ }));
    expect(screen.getByRole('button', { name: /^Companion settings/ })).toHaveAttribute('aria-expanded', 'false');
    first.view.unmount();
    renderPane(makeController());
    expect(screen.getByRole('button', { name: /^Companion settings/ })).toHaveAttribute('aria-expanded', 'false');
  });

  it('collapses the question box to a one-line bar that keeps the draft, and reopens it on click', () => {
    renderPane(makeController());
    const box = screen.getByLabelText('Message to the Companion') as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'half typed question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Collapse the question box' }));
    const bar = screen.getByRole('button', { name: 'Open the question box' });
    expect(bar).toHaveAttribute('aria-expanded', 'false');
    expect(within(bar).getByText('Draft: half typed question')).toBeInTheDocument();
    fireEvent.click(bar);
    expect((screen.getByLabelText('Message to the Companion') as HTMLTextAreaElement).value).toBe('half typed question');
  });

  it('flags a waiting answer on the collapsed bar', () => {
    updateCompanionView('meeting-1', { composerCollapsed: true });
    renderPane(makeController({ pendingAssistantIds: ['a9'] }));
    expect(within(screen.getByRole('button', { name: 'Open the question box' })).getByText('Answering…')).toBeInTheDocument();
  });

  it('counts rows that arrive after the reader last saw the stream on the collapsed bar', () => {
    updateCompanionView('meeting-1', { composerCollapsed: true, lastSeenSeq: 1 });
    renderPane(makeController(timeline({ items: [item('a', 1), item('b', 2), item('c', 3)] })));
    expect(within(screen.getByRole('button', { name: 'Open the question box' })).getByText('2 new')).toBeInTheDocument();
  });

  it('treats the backlog as seen the first time a meeting is shown', () => {
    renderPane(makeController({ ...timeline({ items: [item('a', 1), item('b', 2)] }), baselineSeq: 2 }));
    expect(getCompanionView('meeting-1').lastSeenSeq).toBe(2);
  });

  it('shows the Companion-off setup with earlier items and no stream', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false }, ...timeline({ items: [item('a', 1)] }) }));
    expect(screen.getByRole('button', { name: 'Turn On Companion' })).toBeInTheDocument();
    expect(screen.queryByRole('log')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Companion settings' })).toBeNull();
  });

  it('re-renders a streaming answer in place without duplicating it when it persists', () => {
    const streaming = makeController({ drafts: { a1: 'Partial' } });
    const view = renderPane(streaming);
    expect(screen.getByText('Partial')).toBeInTheDocument();
    act(() => view.rerender(makeController(timeline({ chat: [chat('a1', 3, 'assistant', 'Partial and complete')] }))));
    expect(screen.queryByText('Partial')).toBeNull();
    expect(screen.getByText('Partial and complete')).toBeInTheDocument();
  });
});

function makeLinks(overrides: Partial<CompanionLinks> = {}): CompanionLinks {
  return {
    items: [],
    hoveredItemId: null,
    hover: vi.fn(),
    canShowInTranscript: () => true,
    showInTranscript: vi.fn(),
    showInCompanion: vi.fn(),
    transcriptFocus: null,
    companionFocus: null,
    ...overrides,
  };
}

function renderLinkedPane(controller: CompanionController, links: CompanionLinks) {
  const props = { ui, globalSettings: { settings: null, update: vi.fn(async () => false), refresh: vi.fn(async () => undefined) }, isTargetRecording: true, variant: 'embedded' as const };
  const tree = (value: CompanionLinks, next: CompanionController) => (
    <CompanionLinksProvider value={value}>
      <CompanionPane controller={next} {...props} />
    </CompanionLinksProvider>
  );
  const view = render(tree(links, controller));
  return { view, rerender: (value: CompanionLinks, next: CompanionController = controller) => view.rerender(tree(value, next)) };
}

describe('Companion links from the transcript', () => {
  const populated = () => makeController(timeline({ items: [item('a', 1), item('b', 2)] }));

  it('offers Show in transcript on a card, which asks the link controller and reports hover', () => {
    const links = makeLinks();
    renderLinkedPane(populated(), links);
    const cards = screen.getAllByRole('article');
    fireEvent.click(within(cards[1]).getByRole('button', { name: 'Show in transcript' }));
    expect(links.showInTranscript).toHaveBeenCalledWith(expect.objectContaining({ id: 'b' }));
    fireEvent.mouseEnter(cards[0]);
    expect(links.hover).toHaveBeenCalledWith('a');
    fireEvent.mouseLeave(cards[0]);
    expect(links.hover).toHaveBeenLastCalledWith(null);
  });

  it('hides the link on a card whose lines are not in the transcript, and without any links', () => {
    renderLinkedPane(populated(), makeLinks({ canShowInTranscript: (candidate) => candidate.id === 'a' }));
    const cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByRole('button', { name: 'Show in transcript' })).toBeInTheDocument();
    expect(within(cards[1]).queryByRole('button', { name: 'Show in transcript' })).toBeNull();

    resetCompanionViews();
    cleanup();
    renderPane(populated());
    expect(screen.queryByRole('button', { name: 'Show in transcript' })).toBeNull();
  });

  it('marks the card whose transcript lines are hovered', () => {
    const links = makeLinks();
    const { rerender } = renderLinkedPane(populated(), links);
    rerender({ ...links, hoveredItemId: 'b' });
    const cards = screen.getAllByRole('article');
    expect(cards[1]).toHaveClass('is-linked');
    expect(cards[0]).not.toHaveClass('is-linked');
  });

  it('scrolls to and highlights the card named by a fresh focus, once per request', () => {
    const links = makeLinks();
    const { rerender } = renderLinkedPane(populated(), links);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    rerender({ ...links, companionFocus: { itemId: 'b', key: 'local:1', issuedAt: Date.now() } });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
    expect(document.querySelector('[data-stream-key="item:b"]')).toHaveClass('is-highlighted');
    // A re-render with the same request does not scroll again.
    rerender({ ...links, companionFocus: { itemId: 'b', key: 'local:1', issuedAt: Date.now() } });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
    // Asking for the same card again is a new request.
    rerender({ ...links, companionFocus: { itemId: 'b', key: 'local:2', issuedAt: Date.now() } });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(2);
  });

  it('ignores a focus that was already stale when the pane mounted', () => {
    renderLinkedPane(populated(), makeLinks({ companionFocus: { itemId: 'b', key: 'old', issuedAt: Date.now() - 60_000 } }));
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it('acts on a fresh focus that was waiting when the pane mounted, as in a window that had to open', () => {
    renderLinkedPane(populated(), makeLinks({ companionFocus: { itemId: 'b', key: 'new', issuedAt: Date.now() } }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it('waits for the timeline to load, then gives up quietly when the card is not there', () => {
    const loading = makeController({ phase: 'loading', ...timeline({}) });
    const links = makeLinks({ companionFocus: { itemId: 'b', key: 'k', issuedAt: Date.now() } });
    const { rerender } = renderLinkedPane(loading, links);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    rerender(links, populated());
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);

    cleanup();
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    const missing = makeLinks({ companionFocus: { itemId: 'gone', key: 'k2', issuedAt: Date.now() } });
    const second = renderLinkedPane(populated(), missing);
    second.rerender(missing, makeController(timeline({ items: [item('a', 1), item('b', 2), item('gone', 3, { dismissed: true })] })));
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });
});

describe('Look into this', () => {
  const asked = [chat('q1', 1, 'user', 'What is the Acme renewal term?'), chat('a1', 2, 'assistant', 'I could not find that in the transcript.')];
  const researchOn = { status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, investigate: true } };

  it('offers research on an answer that cited nothing and starts it, quoting the reader message', () => {
    const controller = makeController({ ...researchOn, ...timeline({ chat: asked }) });
    renderPane(controller);
    fireEvent.click(screen.getByRole('button', { name: 'Look into this' }));
    expect(controller.investigate).toHaveBeenCalledWith('What is the Acme renewal term?', 'q1');
  });

  it('is hidden with research off, for a cited answer, once researched, and while an answer is streaming', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, investigate: false }, ...timeline({ chat: asked }) }));
    expect(screen.queryByRole('button', { name: 'Look into this' })).toBeNull();
    cleanup();
    resetCompanionViews();
    renderPane(makeController({ ...researchOn, ...timeline({ chat: [asked[0], chat('a1', 2, 'assistant', 'It caps at five [proj/retry.py:3-9].')] }) }));
    expect(screen.queryByRole('button', { name: 'Look into this' })).toBeNull();
    cleanup();
    resetCompanionViews();
    renderPane(makeController({ ...researchOn, ...timeline({ chat: asked, items: [item('r1', 3, { researched: true, kind: 'answer', reply_to_message_id: 'q1' })] }) }));
    expect(screen.queryByRole('button', { name: 'Look into this' })).toBeNull();
    cleanup();
    resetCompanionViews();
    renderPane(makeController({ ...researchOn, ...timeline({ chat: asked }), pendingAssistantIds: ['a2'] }));
    expect(screen.queryByRole('button', { name: 'Look into this' })).toBeNull();
  });

  it('shows the reader question above the researched answer that replies to it', () => {
    renderPane(makeController({ ...researchOn, ...timeline({ chat: asked, items: [item('r1', 3, { researched: true, kind: 'answer', reply_to_message_id: 'q1' }), item('plain', 4)] }) }));
    const cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByText('In reply to: “What is the Acme renewal term?”')).toBeInTheDocument();
    expect(within(cards[1]).queryByText(/In reply to/)).toBeNull();
  });
});

describe('Dismiss with undo', () => {
  const two = () => makeController(timeline({ items: [item('a', 1), item('b', 2)] }));

  it('offers Undo after a dismissal and restores the note, then scrolls back to it', async () => {
    const controller = two();
    renderPane(controller);
    await act(async () => {
      fireEvent.click(within(screen.getAllByRole('article')[0]).getByRole('button', { name: 'Dismiss' }));
    });
    expect(controller.sendFeedback).toHaveBeenCalledWith('a', 'dismissed');
    const notice = screen.getByText('Note dismissed.').closest('[role="status"]') as HTMLElement;
    await act(async () => {
      fireEvent.click(within(notice).getByRole('button', { name: 'Undo' }));
    });
    expect(controller.sendFeedback).toHaveBeenLastCalledWith('a', 'restored');
    expect(screen.queryByText('Note dismissed.')).toBeNull();
  });

  it('shows no notice when the dismissal was not saved, and none for other feedback', async () => {
    const failing = makeController(timeline({ items: [item('a', 1)] }), { sendFeedback: vi.fn(async () => false) });
    renderPane(failing);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    });
    expect(screen.queryByText('Note dismissed.')).toBeNull();
    cleanup();
    resetCompanionViews();
    const working = makeController(timeline({ items: [item('a', 1)] }));
    renderPane(working);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Pin' }));
    });
    expect(screen.queryByText('Note dismissed.')).toBeNull();
  });

  it('removes the notice after its countdown and with the close button', async () => {
    vi.useFakeTimers();
    try {
      renderPane(two());
      await act(async () => {
        fireEvent.click(within(screen.getAllByRole('article')[0]).getByRole('button', { name: 'Dismiss' }));
      });
      expect(screen.getByText('Note dismissed.')).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(8100);
      });
      expect(screen.queryByText('Note dismissed.')).toBeNull();
      await act(async () => {
        fireEvent.click(within(screen.getAllByRole('article')[1]).getByRole('button', { name: 'Dismiss' }));
      });
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      expect(screen.queryByText('Note dismissed.')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('Kind filter, copy pinned and status label', () => {
  const mixed = () =>
    makeController(
      timeline({
        items: [item('s1', 1, { kind: 'suggestion', text: 'try caching' }), item('a1', 2, { kind: 'answer', text: 'five attempts', pinned: true }), item('i1', 3, { kind: 'insight', text: 'a plain insight' })],
        chat: [chat('q', 4, 'user', 'a question')],
      }),
    );

  it('filters the stream by kind and keeps the reader\'s conversation', () => {
    renderPane(mixed());
    const group = screen.getByRole('group', { name: 'Show' });
    fireEvent.click(within(group).getByRole('button', { name: /^Suggestions/ }));
    const log = screen.getByRole('log');
    expect(within(log).getByText('try caching')).toBeInTheDocument();
    const row = (key: string) => log.querySelector(`[data-stream-key="${key}"]`);
    expect(row('item:a1')?.classList.contains('is-leaving') ?? true).toBe(true);
    expect(row('item:i1')?.classList.contains('is-leaving') ?? true).toBe(true);
    expect(within(log).getByText('a question')).toBeInTheDocument();
    expect(getCompanionView('meeting-1').kindFilter).toBe('suggestion');
    fireEvent.click(within(group).getByRole('button', { name: /^All/ }));
    expect(within(log).getByText('five attempts')).toBeInTheDocument();
  });

  it('disables a kind with nothing in it and says so when the chosen kind empties', () => {
    renderPane(mixed());
    const group = screen.getByRole('group', { name: 'Show' });
    expect(within(group).getByRole('button', { name: /^From your sources/ })).toBeDisabled();
    expect(within(group).getByRole('button', { name: /^Pinned/ })).toBeEnabled();
    expect(screen.queryByText(/Nothing here yet/)).toBeNull();
  });

  it('says nothing is there when the chosen kind has been emptied, and Pinned and counts follow the data', () => {
    const view = renderPane(mixed());
    fireEvent.click(within(screen.getByRole('group', { name: 'Show' })).getByRole('button', { name: /^Pinned/ }));
    view.rerender(makeController(timeline({ items: [item('s1', 1, { kind: 'suggestion' })] })));
    expect(screen.getByText('Nothing here yet. Choose All to see everything.')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'Show' })).getByRole('button', { name: /^Pinned/ })).toBeEnabled();
  });

  it('shows no filter row for an empty stream', () => {
    renderPane(makeController(timeline({ items: [] })));
    expect(screen.queryByRole('group', { name: 'Show' })).toBeNull();
  });

  it('switches back to All when a pinned item the filter hides is jumped to', () => {
    renderPane(mixed());
    fireEvent.click(within(screen.getByRole('group', { name: 'Show' })).getByRole('button', { name: /^Suggestions/ }));
    expect(document.querySelector('[data-stream-key="item:a1"]')?.classList.contains('is-leaving') ?? true).toBe(true);
    fireEvent.click(within(screen.getByRole('region', { name: 'Pinned' })).getByRole('button', { name: /five attempts/ }));
    expect(getCompanionView('meeting-1').kindFilter).toBe('all');
    expect(document.querySelector('[data-stream-key="item:a1"]')).toHaveClass('is-highlighted');
  });

  it('copies every pinned item with its time and kind', () => {
    renderPane(mixed());
    fireEvent.click(screen.getByRole('button', { name: 'Copy pinned items' }));
    expect(copyText).toHaveBeenCalledTimes(1);
    expect(copyText).toHaveBeenCalledWith('[00:00] Answer\nfive attempts');
    expect(screen.getByRole('button', { name: 'Copied pinned items' })).toBeInTheDocument();
  });

  it('says when the Companion last looked, once it has finished a check', () => {
    const busy = makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, evaluating: true } });
    const view = renderPane(busy);
    expect(screen.queryByText(/last checked at/)).toBeNull();
    view.rerender(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, evaluating: false } }));
    expect(screen.getByText(/^Listening, last checked at /)).toBeInTheDocument();
  });
});

describe('Settings fold up when the meeting begins', () => {
  const settingsToggle = () => screen.getByRole('button', { name: /^Companion settings/ });
  const withMeetingTime = (seconds: number) => makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, latest_meeting_time: seconds } });

  function renderRecording(controller: CompanionController) {
    const props = { ui, globalSettings: { settings: null, update: vi.fn(async () => false), refresh: vi.fn(async () => undefined) }, isTargetRecording: true, variant: 'embedded' as const };
    const view = render(<CompanionPane controller={controller} {...props} />);
    return (next: CompanionController) => view.rerender(<CompanionPane controller={next} {...props} />);
  }

  it('folds the first-run settings once the transcript starts, and stays folded', () => {
    const rerender = renderRecording(withMeetingTime(0));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
    rerender(withMeetingTime(4.2));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'false');
    rerender(withMeetingTime(9));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(settingsToggle());
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
    rerender(withMeetingTime(30));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
  });

  it('leaves settings the reader opened before the meeting began', () => {
    const rerender = renderRecording(withMeetingTime(0));
    fireEvent.click(settingsToggle());
    fireEvent.click(settingsToggle());
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
    rerender(withMeetingTime(5));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
  });

  it('does not fold settings in a pane that loads with the meeting already under way', () => {
    const rerender = renderRecording(withMeetingTime(120));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
    rerender(withMeetingTime(125));
    expect(settingsToggle()).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('Send button', () => {
  it('shows only the icon, named for assistive technology and the tooltip', () => {
    renderPane(makeController(timeline({ roots: [root] })));
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toHaveTextContent('');
    expect(send).toHaveAttribute('title', 'Send (Enter)');
    expect(send).toBeDisabled();
  });
});

