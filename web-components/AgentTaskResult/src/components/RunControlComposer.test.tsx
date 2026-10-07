// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  pauseSession: vi.fn(),
  resumeSession: vi.fn(),
  sendRunMessage: vi.fn(),
  pickFiles: vi.fn(),
  filesPicked: null as ((paths: string[]) => void) | null,
}));

vi.mock('../services/api', () => ({
  pauseSession: mocks.pauseSession,
  resumeSession: mocks.resumeSession,
  sendRunMessage: mocks.sendRunMessage,
}));

vi.mock('../services/bridge', () => ({
  pickFiles: mocks.pickFiles,
  registerFilesPickedHandler: (handler: (paths: string[]) => void) => {
    mocks.filesPicked = handler;
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
  [mocks.pauseSession, mocks.resumeSession, mocks.sendRunMessage, mocks.pickFiles].forEach(mock => mock.mockReset());
  mocks.filesPicked = null;
  mocks.pauseSession.mockResolvedValue({ success: true, status: 'pause_requested' });
  mocks.resumeSession.mockResolvedValue({ success: true, status: 'resuming' });
  mocks.sendRunMessage.mockResolvedValue({ success: true, status: 'queued', message_id: 'note-1' });
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
function render(mode: 'running' | 'paused', delivered: ReadonlySet<string> = NONE) {
  act(() => {
    root.render(<RunControlComposer turnTaskId="turn-1" mode={mode} deliveredNoteIds={delivered} />);
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
    expect(() => mocks.filesPicked?.(['/tmp/late'])).not.toThrow();
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
