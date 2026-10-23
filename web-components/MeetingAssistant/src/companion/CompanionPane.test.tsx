import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

const { dropListeners } = vi.hoisted(() => ({
  dropListeners: new Set<(payload: { paths: string[]; source: 'drop' | 'picker' }) => void>(),
}));

vi.mock('../bridge/meetingBridge', () => ({
  copyText: vi.fn(),
  openCompanionWindow: vi.fn(),
  pickCompanionFolder: vi.fn(),
  setAnalysisConfiguration: vi.fn(),
  subscribeFilesDropped: vi.fn((listener: (payload: { paths: string[]; source: 'drop' | 'picker' }) => void) => {
    dropListeners.add(listener);
    return () => {
      dropListeners.delete(listener);
    };
  }),
}));

vi.mock('../../../shared/TokenizedSelect', () => ({
  default: ({ value, ariaLabel, onValueChange }: { value: string; ariaLabel: string; onValueChange: (next: string) => void }) => (
    <button type="button" aria-label={ariaLabel} onClick={() => onValueChange('passive')}>{`select ${value}`}</button>
  ),
}));

vi.mock('../../../shared/ReasoningModelPicker', () => ({
  default: ({ selectedModelId, ariaLabel, onModelChange }: { selectedModelId?: string; ariaLabel?: string; onModelChange: (id: string) => void }) => (
    <button type="button" aria-label={ariaLabel} onClick={() => onModelChange('model-x')}>{`picker ${selectedModelId ?? 'none'}`}</button>
  ),
}));

import { copyText, openCompanionWindow, pickCompanionFolder, setAnalysisConfiguration } from '../bridge/meetingBridge';
import CompanionPane from './CompanionPane';
import { resetCompanionViews } from './companionViewStore';
import CompanionToggle from './CompanionToggle';
import { emptyTimelineState } from './companionReducer';
import { initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import type { CompanionController } from './useCompanion';
import { EMPTY_COMPANION_STATUS, type CompanionItem, type CompanionRoot, type CompanionWatch } from './types';

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

function withTimeline(timeline: Partial<typeof emptyTimelineState>): Partial<CompanionStoreState> {
  return { timeline: { ...emptyTimelineState, ...timeline } };
}

function renderPane(controller: CompanionController, options: { isTargetRecording?: boolean; variant?: 'embedded' | 'detached'; onClose?: () => void } = {}) {
  return render(
    <CompanionPane ui={ui} controller={controller} globalSettings={{ settings: null, update: vi.fn(async () => false), refresh: vi.fn(async () => undefined) }} isTargetRecording={options.isTargetRecording ?? true} variant={options.variant ?? 'embedded'} onClose={options.onClose} />,
  );
}

function deliver(paths: string[], source: 'drop' | 'picker') {
  act(() => {
    for (const listener of Array.from(dropListeners)) listener({ paths, source });
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  dropListeners.clear();
  resetCompanionViews();
});

/** The Companion's controls live in a section above the stream that stays closed once something is configured. */
function openSettings() {
  const toggle = screen.getByRole('button', { name: /^Companion settings/ });
  if (toggle.getAttribute('aria-expanded') === 'false') fireEvent.click(toggle);
}

describe('CompanionPane states', () => {
  it('offers to turn the Companion on while recording and calls enable', async () => {
    const controller = makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false } });
    renderPane(controller);
    expect(screen.getByTestId('companion-drop-zone')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Turn On Companion' }));
    });
    expect(controller.enable).toHaveBeenCalledTimes(1);
  });

  it('is read-only for a saved meeting except for sources: no enable button, no composer, but an attachments area', () => {
    const controller = makeController({
      status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false },
      ...withTimeline({ items: [item('a', 'Saved insight', 10)] }),
    });
    renderPane(controller, { isTargetRecording: false });
    expect(screen.getByText('Saved notes')).toBeInTheDocument();
    expect(screen.getByText(/Saved Companion notes from this meeting/)).toBeInTheDocument();
    expect(screen.getByText('Saved insight')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Turn On Companion' })).toBeNull();
    expect(screen.queryByLabelText('Message to the Companion')).toBeNull();
    expect(screen.queryByText(/picker/)).toBeNull();
    openSettings();
    expect(screen.getByTestId('companion-drop-zone')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Attachments / References' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Attach files or folders' })).toBeInTheDocument();
  });

  it('shows a loading note, an idle note, and a retryable error', () => {
    const loading = renderPane(makeController({ phase: 'loading' }));
    expect(screen.getByText('Loading the Companion…')).toBeInTheDocument();
    loading.unmount();
    const idle = renderPane(makeController({ phase: 'idle' }));
    expect(screen.getByText('Waiting for the Basil backend…')).toBeInTheDocument();
    idle.unmount();
    const controller = makeController({ phase: 'error', loadError: 'Basil could not reach its backend.' });
    renderPane(controller);
    expect(screen.getByText('Basil could not reach its backend.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(controller.refresh).toHaveBeenCalledTimes(1);
  });

  it('shows a plain-language banner and the Paused status when capacity is exhausted', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, capacity: 'paused', capacity_reason: 'lag' } }));
    expect(screen.getByText('Paused')).toBeInTheDocument();
    expect(screen.getByText(/paused itself because transcription is falling behind/)).toBeInTheDocument();
    expect(screen.queryByText('lag')).toBeNull();
  });

  it('shows the backend error text and clears it on Dismiss', () => {
    const controller = makeController({}, { actionError: 'That folder is not allowed.' });
    renderPane(controller);
    const alert = screen.getByText('That folder is not allowed.').closest('[role="alert"]') as HTMLElement;
    fireEvent.click(within(alert).getByRole('button', { name: 'Dismiss' }));
    expect(controller.clearActionError).toHaveBeenCalledTimes(1);
  });

  it('keeps a reload failure visible once the pane is already ready', () => {
    const controller = makeController({ loadError: 'Refresh failed.' });
    renderPane(controller);
    const alert = screen.getByText('Refresh failed.').closest('[role="alert"]') as HTMLElement;
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    expect(controller.refresh).toHaveBeenCalledTimes(1);
  });
});

describe('CompanionPane header and controls', () => {
  it('offers Detach and Hide only in the embedded pane', () => {
    const onClose = vi.fn();
    const embedded = renderPane(makeController(), { onClose });
    fireEvent.click(screen.getByRole('button', { name: 'Detach Companion' }));
    expect(openCompanionWindow).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Hide the Companion' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    embedded.unmount();
    renderPane(makeController(), { variant: 'detached' });
    expect(screen.queryByRole('button', { name: 'Detach Companion' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hide the Companion' })).toBeNull();
  });

  it('routes the shared model picker through the analysis configuration, only while recording', () => {
    const live = renderPane(makeController());
    fireEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    expect(setAnalysisConfiguration).toHaveBeenCalledWith({ modelId: 'model-x' });
    live.unmount();
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } }), { isTargetRecording: false });
    expect(screen.queryByRole('button', { name: 'Reasoning model' })).toBeNull();
  });

  it('has no mode row of its own, since the mode select sits beside the Companion switch', () => {
    renderPane(makeController());
    expect(screen.queryByRole('button', { name: 'Companion mode' })).toBeNull();
    expect(screen.queryByText('Mode:')).toBeNull();
    expect(screen.queryByRole('button', { name: /turn off/i })).toBeNull();
  });

  it('explains passive mode in the empty feed', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true, mode: 'passive' } }));
    expect(screen.getByText('Passive mode: the Companion answers when you ask.')).toBeInTheDocument();
  });
});

describe('CompanionPane feed', () => {
  const items = [
    item('a', 'Alpha', 90, { seq: 1 }),
    item('b', 'Bravo', 30, { pinned: true, seq: 2 }),
    item('c', 'Charlie', 20, { dismissed: true, seq: 3 }),
  ];

  it('lists items in arrival order with the newest last, keeps a pinned item in place, hides dismissed ones, and can reveal them', () => {
    const controller = makeController(withTimeline({ items }));
    renderPane(controller);
    const order = screen.getAllByRole('article').map((article) => article.textContent ?? '');
    expect(order[0]).toContain('Alpha');
    expect(order[1]).toContain('Bravo');
    expect(order).toHaveLength(2);
    expect(screen.queryByText('Charlie')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show dismissed (1)' }));
    expect(screen.getByText('Charlie')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide dismissed' })).toBeInTheDocument();
  });

  it('sends pin, unpin, dismiss and rating feedback for the right item', () => {
    const controller = makeController(withTimeline({ items }));
    renderPane(controller);
    const [alpha, bravo] = screen.getAllByRole('article');
    fireEvent.click(within(alpha).getByRole('button', { name: 'Pin' }));
    fireEvent.click(within(bravo).getByRole('button', { name: 'Unpin' }));
    fireEvent.click(within(alpha).getByRole('button', { name: 'Dismiss' }));
    fireEvent.click(within(alpha).getByRole('button', { name: 'Helpful' }));
    fireEvent.click(within(alpha).getByRole('button', { name: 'Not helpful' }));
    expect(controller.sendFeedback).toHaveBeenNthCalledWith(1, 'a', 'pinned');
    expect(controller.sendFeedback).toHaveBeenNthCalledWith(2, 'b', 'unpinned');
    expect(controller.sendFeedback).toHaveBeenNthCalledWith(3, 'a', 'dismissed');
    expect(controller.sendFeedback).toHaveBeenNthCalledWith(4, 'a', 'useful');
    expect(controller.sendFeedback).toHaveBeenNthCalledWith(5, 'a', 'not_useful');
    expect(within(alpha).getByRole('button', { name: 'Not helpful' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('copies the item with its sources and records the copy', () => {
    const cited = item('d', 'Delta', 40, {
      kind: 'answer',
      citations: [{ path: 'src/retry.py', line_start: 12, line_end: 20, excerpt: 'def backoff(attempt):' }],
    });
    const controller = makeController(withTimeline({ items: [cited] }));
    renderPane(controller);
    expect(screen.getByText('1 source')).toBeInTheDocument();
    expect(screen.getByText('src/retry.py:12-20')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(copyText).toHaveBeenCalledWith('Delta\n\nSources:\n- src/retry.py:12-20');
    expect(controller.sendFeedback).toHaveBeenCalledWith('d', 'copied');
  });

  it('labels watch-triggered, truncated and unsourced items', () => {
    const watched = item('w', 'Watched note', 50, { watch_id: 'w1', truncated: true, no_source: true });
    const controller = makeController(withTimeline({
      items: [watched],
      watches: [{ id: 'w1', topic: 'billing', instruction: '', keywords: [], created_at: 0, active: true, last_triggered_at: 50 }],
    }));
    renderPane(controller);
    expect(screen.getByText('Watch: billing')).toBeInTheDocument();
    expect(screen.getByText('This answer was cut short to fit.')).toBeInTheDocument();
    expect(screen.getByText('Not from your files. Based on the conversation alone.')).toBeInTheDocument();
  });

  it('keeps earlier items visible in the off state while recording', () => {
    const controller = makeController({
      status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false },
      ...withTimeline({ items: [item('a', 'Alpha', 10)] }),
    });
    renderPane(controller);
    expect(screen.getByText('Earlier in this meeting')).toBeInTheDocument();
    expect(screen.getByText('Alpha')).toBeInTheDocument();
  });
});

describe('CompanionPane sources', () => {
  it('accepts a Finder drop only after the zone was armed, and only once', () => {
    const controller = makeController();
    renderPane(controller);
    deliver(['/tmp/unarmed'], 'drop');
    expect(controller.addRoots).not.toHaveBeenCalled();
    fireEvent.dragEnter(screen.getByTestId('companion-drop-zone'));
    deliver(['/tmp/proj'], 'drop');
    expect(controller.addRoots).toHaveBeenCalledWith(['/tmp/proj']);
    deliver(['/tmp/again'], 'drop');
    expect(controller.addRoots).toHaveBeenCalledTimes(1);
  });

  it('disarms when the pointer leaves the zone', () => {
    const controller = makeController();
    renderPane(controller);
    const zone = screen.getByTestId('companion-drop-zone');
    fireEvent.dragEnter(zone);
    fireEvent.dragLeave(zone);
    deliver(['/tmp/proj'], 'drop');
    expect(controller.addRoots).not.toHaveBeenCalled();
  });

  it('always accepts the folder picker and opens it from the Attach files or folders button', () => {
    const controller = makeController();
    renderPane(controller);
    fireEvent.click(screen.getByRole('button', { name: 'Attach files or folders' }));
    expect(pickCompanionFolder).toHaveBeenCalledTimes(1);
    deliver(['/tmp/picked'], 'picker');
    expect(controller.addRoots).toHaveBeenCalledWith(['/tmp/picked']);
  });

  it('listens for drops on a saved meeting so a source can be added after the call ends', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } }), { isTargetRecording: false });
    expect(dropListeners.size).toBe(1);
  });

  it('adds a dropped source to a saved meeting once the zone was armed', () => {
    const controller = makeController({ status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } });
    renderPane(controller, { isTargetRecording: false });
    openSettings();
    deliver(['/tmp/unarmed'], 'drop');
    expect(controller.addRoots).not.toHaveBeenCalled();
    fireEvent.dragEnter(screen.getByTestId('companion-drop-zone'));
    deliver(['/tmp/repo'], 'drop');
    expect(controller.addRoots).toHaveBeenCalledWith(['/tmp/repo']);
  });

  it('stays armed through the DOM drop event so the native paths callback still lands', () => {
    const controller = makeController();
    renderPane(controller);
    const zone = screen.getByTestId('companion-drop-zone');
    fireEvent.dragEnter(zone);
    fireEvent.drop(zone);
    deliver(['/tmp/after-drop'], 'drop');
    expect(controller.addRoots).toHaveBeenCalledWith(['/tmp/after-drop']);
  });

  it('lists attached and queued sources with removal actions', () => {
    const root: CompanionRoot = { id: 'r1', path: '/tmp/proj', display_name: 'proj', kind: 'folder', attached_at: 0, detached_at: null };
    const controller = makeController(withTimeline({ roots: [root] }), { pendingRoots: ['/tmp/queued/notes'] });
    renderPane(controller);
    openSettings();
    fireEvent.click(screen.getByRole('button', { name: 'Remove proj' }));
    expect(controller.removeRoot).toHaveBeenCalledWith('r1');
    expect(screen.getByText('notes')).toBeInTheDocument();
    expect(screen.getByTitle('Queued until the Companion is on: /tmp/queued/notes')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove queued /tmp/queued/notes' }));
    expect(controller.removePendingRoot).toHaveBeenCalledWith('/tmp/queued/notes');
  });
});

describe('CompanionPane watches', () => {
  const watch: CompanionWatch = { id: 'w1', topic: 'pricing', instruction: 'Show the tiers', keywords: ['pricing'], created_at: 5, active: true, last_triggered_at: 65 };

  it('lists active watches, shows when one last fired, and stops a watch', () => {
    const controller = makeController(withTimeline({ watches: [watch, { ...watch, id: 'w2', topic: 'old', active: false }] }));
    renderPane(controller);
    openSettings();
    expect(screen.getByText('pricing')).toBeInTheDocument();
    expect(screen.queryByText('old')).toBeNull();
    expect(screen.getByText('Last surfaced at [01:05]')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Stop watching pricing' }));
    expect(controller.cancelWatch).toHaveBeenCalledWith('w1');
  });

  it('creates a watch from the form and clears it after success', async () => {
    const controller = makeController();
    renderPane(controller);
    const add = screen.getByRole('button', { name: 'Add Watch' });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Watch topic'), { target: { value: '  billing  ' } });
    fireEvent.change(screen.getByLabelText('What to surface'), { target: { value: 'Summarize the endpoint' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Add Watch' }));
    });
    expect(controller.createWatch).toHaveBeenCalledWith('billing', 'Summarize the endpoint');
    expect((screen.getByLabelText('Watch topic') as HTMLInputElement).value).toBe('');
  });

  it('keeps the form text when the backend rejects the watch', async () => {
    const controller = makeController({}, { createWatch: vi.fn(async () => false) });
    renderPane(controller);
    fireEvent.change(screen.getByLabelText('Watch topic'), { target: { value: 'billing' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Add Watch' }));
    });
    expect((screen.getByLabelText('Watch topic') as HTMLInputElement).value).toBe('billing');
  });

  it('hides the watch section for a saved meeting without watches', () => {
    renderPane(makeController({ status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false } }), { isTargetRecording: false });
    expect(screen.queryByText('Watching for')).toBeNull();
  });
});

describe('CompanionPane chat', () => {
  it('sends on Enter, clears after acceptance, and does not send on Shift+Enter or an empty draft', async () => {
    const controller = makeController();
    renderPane(controller);
    const box = screen.getByLabelText('Message to the Companion') as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'hello there' } });
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(controller.sendChat).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(controller.sendChat).toHaveBeenCalledWith('hello there');
    expect(box.value).toBe('');
    await act(async () => {
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(controller.sendChat).toHaveBeenCalledTimes(1);
  });

  it('keeps the typed text when the backend rejects the message', async () => {
    const controller = makeController({}, { sendChat: vi.fn(async () => false) });
    renderPane(controller);
    const box = screen.getByLabelText('Message to the Companion') as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'try again' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    });
    expect(box.value).toBe('try again');
  });

  it('renders history, a streaming draft and a pending answer', () => {
    const controller = makeController({
      ...withTimeline({
        chat: [
          { id: 'u1', role: 'user', text: 'Why retries?', meeting_time: 1, truncated: false, status: 'complete', seq: 0 },
          { id: 'a0', role: 'assistant', text: 'Flaky upstream.', meeting_time: 2, truncated: false, status: 'complete', seq: 0 },
          { id: 'a9', role: 'assistant', text: 'Half', meeting_time: 3, truncated: true, status: 'error', seq: 0 },
        ],
      }),
      drafts: { a1: 'Partial answer' },
      pendingAssistantIds: ['a2'],
    });
    renderPane(controller);
    expect(screen.getByText('Why retries?')).toBeInTheDocument();
    expect(screen.getByText('Flaky upstream.')).toBeInTheDocument();
    expect(screen.getByText('That answer could not be completed.')).toBeInTheDocument();
    expect(screen.getByText('Partial answer')).toBeInTheDocument();
    expect(screen.getByText('Thinking…')).toBeInTheDocument();
  });

  it('keeps history readable but disables the composer when the Companion is not live', () => {
    const controller = makeController({
      status: { ...EMPTY_COMPANION_STATUS, live: false, enabled: false },
      ...withTimeline({ chat: [{ id: 'u1', role: 'user', text: 'Earlier question', meeting_time: 1, truncated: false, status: 'complete', seq: 0 }] }),
    });
    renderPane(controller, { isTargetRecording: false });
    expect(screen.getByText('Earlier question')).toBeInTheDocument();
    expect(screen.queryByLabelText('Message to the Companion')).toBeNull();
    expect(screen.getByText(/Chat is available while the meeting is recording/)).toBeInTheDocument();
  });

  it('caps the composer at the backend limit', () => {
    renderPane(makeController());
    expect(screen.getByLabelText('Message to the Companion')).toHaveAttribute('maxlength', '4000');
  });
});

describe('CompanionToggle', () => {
  it('reports the new value and disables the switch while busy', () => {
    const onChange = vi.fn();
    const view = render(<CompanionToggle enabled={false} busy={false} onChange={onChange} />);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onChange).toHaveBeenCalledWith(true);
    expect(screen.queryByRole('button', { name: 'Show the Companion' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Companion mode' })).toBeNull();
    view.rerender(<CompanionToggle enabled busy onChange={onChange} />);
    expect(screen.getByRole('checkbox')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Show the Companion' })).toBeNull();
  });

  it('shows what is waiting in the hidden pane beside the switch, and nothing otherwise', () => {
    const view = render(<CompanionToggle enabled busy={false} onChange={vi.fn()} badge="2 new" />);
    expect(screen.getByRole('status')).toHaveTextContent('2 new');
    view.rerender(<CompanionToggle enabled busy={false} onChange={vi.fn()} badge={null} />);
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('CompanionToggle mode select', () => {
  it('appears to the right of the switch only while the Companion is on and the mode is known', () => {
    const onMode = vi.fn();
    const mode = { value: 'active' as const, onChange: onMode };
    const view = render(<CompanionToggle enabled={false} busy={false} onChange={vi.fn()} mode={mode} />);
    expect(screen.queryByRole('button', { name: 'Companion mode' })).toBeNull();
    view.rerender(<CompanionToggle enabled busy={false} onChange={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Companion mode' })).toBeNull();
    view.rerender(<CompanionToggle enabled busy={false} onChange={vi.fn()} mode={mode} />);
    const select = screen.getByRole('button', { name: 'Companion mode' });
    expect(screen.getByRole('checkbox').compareDocumentPosition(select) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(select);
    expect(onMode).toHaveBeenCalledWith('passive');
  });
});

describe('CompanionPane Considered view', () => {
  const ledger = {
    evaluations: [
      { id: 'ev-1', seq: 1, kind: 'evaluation' as const, meeting_time: 30, wall_time: '2026-01-01T00:00:00Z', payload: { trigger: 'periodic', considered: 'Small talk, nothing to add.', kept: 0, candidates: [] } },
    ],
    evaluationTotal: 67,
    items: [item('a', 'A note the Companion wrote.', 40, { seq: 2, rationale: 'Nobody owns the follow-up.' })],
  };

  it('does not count a to-do or agent card made from a note as the Companion speaking', () => {
    const card = { ...item('card', 'To-Do from a note', 50, { seq: 3 }), kind: 'proposal' as const };
    renderPane(makeController(withTimeline({ ...ledger, items: [...ledger.items, card] })));
    expect(screen.getByText('Considered 67 times, spoke 1')).toBeTruthy();
  });

  it('always shows the counter, keeps the rows hidden until asked, and shows the rationale on the card', async () => {
    renderPane(makeController(withTimeline(ledger)));
    expect(screen.getByText('Considered 67 times, spoke 1')).toBeTruthy();
    expect(screen.queryByText('Small talk, nothing to add.')).toBeNull();
    expect(screen.getByText('Nobody owns the follow-up.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show what it considered' }));
    expect(screen.getByText('Small talk, nothing to add.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Hide what it considered' }));
    await waitFor(() => expect(screen.queryByText('Small talk, nothing to add.')).toBeNull());
  });

  it('shows no counter before the first evaluation', () => {
    renderPane(makeController(withTimeline({ items: ledger.items })));
    expect(screen.queryByText(/^Considered /)).toBeNull();
  });
});
