// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  pauseSession: vi.fn(),
  resumeSession: vi.fn(),
  sendRunMessage: vi.fn(),
  getReasoningModels: vi.fn(),
  pickFiles: vi.fn(),
  filesPicked: null as ((paths: string[]) => void) | null,
}));

vi.mock('../services/api', () => ({
  pauseSession: mocks.pauseSession,
  resumeSession: mocks.resumeSession,
  sendRunMessage: mocks.sendRunMessage,
  getReasoningModels: mocks.getReasoningModels,
}));

vi.mock('../services/bridge', () => ({
  pickFiles: mocks.pickFiles,
  registerFilesPickedHandler: (handler: (paths: string[]) => void) => {
    mocks.filesPicked = handler;
    return () => {
      if (mocks.filesPicked === handler) mocks.filesPicked = null;
    };
  },
}));

let RunControlComposer: typeof import('./RunControlComposer').default;
let container: HTMLDivElement;
let root: Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  RunControlComposer = (await import('./RunControlComposer')).default;
});

beforeEach(() => {
  [mocks.pauseSession, mocks.resumeSession, mocks.sendRunMessage, mocks.getReasoningModels, mocks.pickFiles].forEach(mock => mock.mockReset());
  mocks.filesPicked = null;
  mocks.pauseSession.mockResolvedValue({ success: true, status: 'pause_requested' });
  mocks.resumeSession.mockResolvedValue({ success: true, status: 'resuming' });
  mocks.sendRunMessage.mockResolvedValue({ success: true, status: 'queued', message_id: 'note-1' });
  mocks.getReasoningModels.mockResolvedValue({
    current_model: 'claude-opus',
    api_models_enabled: true,
    models: [
      { id: 'claude-opus', name: 'claude-opus', display_name: 'Claude Opus', category: 'api' },
      { id: 'Qwen-qwen35-4b-q4km', name: 'Qwen-qwen35-4b-q4km', display_name: 'Qwen 3.5 4B', category: 'local' },
    ],
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const NONE: ReadonlySet<string> = new Set();

function editor(): HTMLDivElement {
  const element = container.querySelector<HTMLDivElement>('[role="textbox"]');
  if (!element) throw new Error('Expected the note box.');
  return element;
}

// jsdom does not implement innerText, which the composer reads in browsers.
function render(mode: 'running' | 'paused', delivered: ReadonlySet<string> = NONE, connectionLost = false) {
  act(() => {
    root.render(
      <RunControlComposer turnTaskId="turn-1" mode={mode} deliveredNoteIds={delivered} connectionLost={connectionLost} />,
    );
  });
  const element = editor();
  if (!Object.getOwnPropertyDescriptor(element, 'innerText')) {
    Object.defineProperty(element, 'innerText', { configurable: true, get: () => element.textContent ?? '' });
  }
}

function button(label: string): HTMLButtonElement {
  const match = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  if (!match) throw new Error(`Expected a "${label}" button.`);
  return match;
}

function type(value: string) {
  act(() => {
    editor().textContent = value;
    editor().dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function pressCommandReturn() {
  await act(async () => {
    editor().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true, cancelable: true }));
    await Promise.resolve();
    await Promise.resolve();
  });
}

function attach(...paths: string[]) {
  act(() => mocks.filesPicked?.(paths));
}

async function click(target: HTMLButtonElement) {
  await act(async () => {
    target.click();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('RunControlComposer while running', () => {
  it('is the regular rich follow-up box with an icon-only Pause that explains itself in a tooltip', () => {
    render('running');

    expect(container.querySelector('.text-followup .rich-text-composer-toolbar')).not.toBeNull();
    expect(editor().getAttribute('data-placeholder')).toBe('Send Basil a note while it works…');
    const pause = button('Pause');
    expect(pause.textContent).toBe('');
    expect(pause.querySelector('svg')).not.toBeNull();
    expect(pause.title).toBe('Pause after the current step');
    expect(container.querySelector('textarea')).toBeNull();
  });

  it('keeps Send disabled until there is a note', () => {
    render('running');
    expect(button('Send').disabled).toBe(true);
    type('   ');
    expect(button('Send').disabled).toBe(true);
    type('Use the Paris office');
    expect(button('Send').disabled).toBe(false);
  });

  it('sends a note with Command-Return, lists it as queued, and drops it once Basil has read it', async () => {
    render('running');
    type('Use the Paris office');
    await pressCommandReturn();

    expect(mocks.sendRunMessage).toHaveBeenCalledWith('turn-1', 'Use the Paris office', []);
    expect(editor().textContent).toBe('');
    expect(container.querySelector('[aria-label="Notes waiting for Basil"]')?.textContent).toContain('Use the Paris office');

    render('running', new Set(['note-1']));
    expect(container.querySelector('[aria-label="Notes waiting for Basil"]')).toBeNull();
  });

  it('does not send an empty note', async () => {
    render('running');
    await pressCommandReturn();
    expect(mocks.sendRunMessage).not.toHaveBeenCalled();
  });

  it('keeps the draft and shows the reason in plain words when the note is refused', async () => {
    mocks.sendRunMessage.mockRejectedValue(new Error('This run is not taking notes right now. (409)'));
    render('running');
    type('Use the Paris office');
    await click(button('Send'));

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('This run is not taking notes right now.');
    expect(editor().textContent).toBe('Use the Paris office');
    expect(container.querySelector('[aria-label="Notes waiting for Basil"]')).toBeNull();
  });

  it('refuses a note over the length limit without calling the server', async () => {
    render('running');
    type('x'.repeat(4001));
    await click(button('Send'));

    expect(mocks.sendRunMessage).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Notes can be up to 4,000 characters.');
  });

  it('asks to pause once and says it will pause after the current step', async () => {
    render('running');
    await click(button('Pause'));

    expect(mocks.pauseSession).toHaveBeenCalledWith('turn-1');
    const pausing = button('Pausing after this step');
    expect(pausing.disabled).toBe(true);
    expect(pausing.title).toBe('Pausing after this step');
  });

  it('shows a fallback message when pausing fails without a reason', async () => {
    mocks.pauseSession.mockRejectedValue('network down');
    render('running');
    await click(button('Pause'));

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Basil could not pause.');
    expect(button('Pause').disabled).toBe(false);
  });
});

describe('RunControlComposer attachments', () => {
  it('offers the regular attach button and opens the file picker', async () => {
    render('running');
    await click(button('Attach files or folders'));
    expect(mocks.pickFiles).toHaveBeenCalledTimes(1);
  });

  it('lists picked or dropped paths once each and lets the user remove one', () => {
    render('running');
    attach('/Users/me/Projects', '/Users/me/notes.md');
    attach('/Users/me/Projects');

    const text = () => container.querySelector('.text-followup-references')?.textContent ?? '';
    expect(text()).toContain('Projects');
    expect(text()).toContain('notes.md');
    expect(container.querySelectorAll('.text-followup-references button')).toHaveLength(2);

    act(() => button('Remove Projects').click());
    expect(text()).not.toContain('Projects');
    expect(text()).toContain('notes.md');
  });

  it('draws the shared drop highlight over the composer while a file drag is over it', () => {
    render('running');
    const zone = container.querySelector('[data-run-control-mode="running"]') as HTMLElement;
    expect(zone.classList.contains('attachment-drop-zone')).toBe(true);
    act(() => {
      zone.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).toContain('Drop files here');
    act(() => {
      zone.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).not.toContain('Drop files here');
  });

  it('sends the attached paths with the note, shows how many are queued, and clears them', async () => {
    render('running');
    attach('/Users/me/Projects');
    type('Start with this folder');
    await click(button('Send'));

    expect(mocks.sendRunMessage).toHaveBeenCalledWith('turn-1', 'Start with this folder', ['/Users/me/Projects']);
    expect(container.querySelector('.run-control-queued-files')?.textContent).toBe('1 file');
    expect(container.querySelector('.text-followup-references')).toBeNull();
  });

  it('keeps the attachments when the note is refused', async () => {
    mocks.sendRunMessage.mockRejectedValue(new Error('Nope (409)'));
    render('running');
    attach('/Users/me/Projects');
    type('Start with this folder');
    await click(button('Send'));

    expect(container.querySelector('.text-followup-references')?.textContent).toContain('Projects');
  });

  it('keeps attachments across the switch to paused and stops listening when unmounted', () => {
    render('running');
    attach('/Users/me/Projects');
    render('paused');
    expect(container.querySelector('.text-followup-references')?.textContent).toContain('Projects');

    act(() => root.render(<div />));
    expect(mocks.filesPicked).toBeNull();
  });
});

describe('RunControlComposer while paused', () => {
  it('shows one paused state and offers only an icon Resume', () => {
    render('paused');

    expect(container.querySelector('[role="status"]')?.textContent).toBe('Paused');
    expect(editor().getAttribute('data-placeholder')).toBe('Paused. Add a note if you like, then resume…');
    const resume = button('Resume');
    expect(resume.textContent).toBe('');
    expect(resume.title).toBe('Resume (⌘↩)');
    expect(container.querySelector('button[aria-label="Pause"]')).toBeNull();
    expect(container.querySelector('button[aria-label="Send"]')).toBeNull();
  });

  it('resumes with the optional note and then locks the box', async () => {
    render('paused');
    type('Skip the PDF');
    expect(button('Resume').title).toBe('Resume with your note (⌘↩)');
    await click(button('Resume'));

    expect(mocks.resumeSession).toHaveBeenCalledWith('turn-1', 'Skip the PDF', []);
    expect(button('Resume').disabled).toBe(true);
    expect(editor().getAttribute('contenteditable')).toBe('false');
  });

  it('resumes without a note when the box is empty', async () => {
    render('paused');
    await pressCommandReturn();

    expect(mocks.resumeSession).toHaveBeenCalledWith('turn-1', undefined, []);
  });

  it('can resume with only an attached file and no typed note', async () => {
    render('paused');
    attach('/Users/me/Projects');
    expect(button('Resume').title).toBe('Resume with your note (⌘↩)');
    await click(button('Resume'));

    expect(mocks.resumeSession).toHaveBeenCalledWith('turn-1', undefined, ['/Users/me/Projects']);
  });

  it('lets the user try again when resuming is refused', async () => {
    mocks.resumeSession.mockRejectedValue(new Error('This run is already resuming. (409)'));
    render('paused');
    await click(button('Resume'));

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('This run is already resuming.');
    expect(button('Resume').disabled).toBe(false);
  });

  it('keeps an unsent draft when the run pauses underneath it', () => {
    render('running');
    type('Remember the Paris office');

    render('paused');

    expect(editor().textContent).toBe('Remember the Paris office');
    expect(button('Resume').title).toBe('Resume with your note (⌘↩)');
  });
});

describe('RunControlComposer after a lost connection', () => {
  const switchToggle = () => {
    const match = [...container.querySelectorAll<HTMLButtonElement>('button.run-control-switch-toggle')][0];
    if (!match) throw new Error('Expected the model switch toggle.');
    return match;
  };

  async function flush() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it('says the connection was lost instead of claiming a pause, and resumes with the same model by default', async () => {
    render('paused', NONE, true);

    expect(container.querySelector('[role="status"]')?.textContent).toBe('Connection lost');
    expect(container.querySelector('[role="status"]')?.classList.contains('run-control-status--connection-lost')).toBe(true);
    expect(editor().getAttribute('data-placeholder')).toContain('Basil lost its connection');
    expect(switchToggle().textContent).toBe('Continue with a different model…');
    expect(mocks.getReasoningModels).not.toHaveBeenCalled();

    await click(button('Resume'));

    expect(mocks.resumeSession).toHaveBeenCalledWith('turn-1', undefined, []);
  });

  it('keeps a user pause free of the model switch', () => {
    render('paused');

    expect(container.querySelector('.run-control-switch-toggle')).toBeNull();
    expect(container.querySelector('.run-control-switch-note')).toBeNull();
  });

  it('asks for a model first, explains the new limited run, and then resumes with the chosen model', async () => {
    render('paused', NONE, true);

    await click(switchToggle());
    await flush();

    expect(mocks.getReasoningModels).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.run-control-switch-note')?.textContent).toContain('new, more limited run');
    expect(button('Resume').disabled).toBe(true);
    expect(button('Resume').title).toBe('Choose a model to continue with');

    await click(button('Model to continue with'));
    const option = [...document.body.querySelectorAll<HTMLButtonElement>('[role="option"]')]
      .find(candidate => candidate.textContent?.includes('Qwen 3.5 4B'));
    if (!option) throw new Error('Expected the local model in the menu.');
    await click(option);

    expect(button('Resume').disabled).toBe(false);
    await click(button('Resume'));

    expect(mocks.resumeSession).toHaveBeenCalledWith('turn-1', undefined, [], 'Qwen-qwen35-4b-q4km');
  });

  it('goes back to the same model when the user changes their mind', async () => {
    render('paused', NONE, true);
    await click(switchToggle());
    await flush();
    expect(switchToggle().textContent).toBe('Use the same model');

    await click(switchToggle());

    expect(switchToggle().textContent).toBe('Continue with a different model…');
    expect(container.querySelector('.run-control-switch-note')).toBeNull();
    expect(button('Resume').disabled).toBe(false);
    await click(button('Resume'));
    expect(mocks.resumeSession).toHaveBeenCalledWith('turn-1', undefined, []);
  });
});
