// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AttachedFilesDisplay from './AttachedFilesDisplay';
import AttachedFilesEditor from './AttachedFilesEditor';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  filesPickedHandler: null as ((paths: string[]) => void) | null,
  registerFilesPickedHandler: vi.fn<(handler: (paths: string[]) => void) => () => void>(),
  pickFiles: vi.fn(),
  openFile: vi.fn(),
  openContainingFolder: vi.fn(),
}));

vi.mock('../../services/bridge', () => ({
  registerFilesPickedHandler: mocks.registerFilesPickedHandler,
  pickFiles: mocks.pickFiles,
  openFile: mocks.openFile,
  openContainingFolder: mocks.openContainingFolder,
}));

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  mocks.registerFilesPickedHandler.mockImplementation((handler) => {
    mocks.filesPickedHandler = handler;
    return () => {
      mocks.filesPickedHandler = null;
    };
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

describe('AttachedFilesEditor', () => {
  it('shows the shared heading, the Add button and the scheduled-run empty text, and opens the picker', () => {
    act(() => root.render(<AttachedFilesEditor paths={[]} onChange={vi.fn()} />));
    expect(container.textContent).toContain('Attachments / References');
    expect(container.textContent).toContain('Attached items are included as context every time this scheduled task runs.');
    const add = container.querySelector('button[aria-label="Attach files or folders"]') as HTMLButtonElement;
    act(() => add.click());
    expect(mocks.pickFiles).toHaveBeenCalledTimes(1);
  });

  it('merges picked or dropped paths without duplicates or blanks and ignores a batch that adds nothing', () => {
    const onChange = vi.fn();
    act(() => root.render(<AttachedFilesEditor paths={['/a/one.txt']} onChange={onChange} />));
    act(() => mocks.filesPickedHandler?.(['/a/one.txt', '/b/two/', '']));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenLastCalledWith(['/a/one.txt', '/b/two/']);
    act(() => mocks.filesPickedHandler?.(['/a/one.txt']));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('removes one attachment by its position', () => {
    const onChange = vi.fn();
    act(() => root.render(<AttachedFilesEditor paths={['/a/one.txt', '/b/two.txt']} onChange={onChange} />));
    const remove = container.querySelector('[aria-label="Remove one.txt"]') as HTMLButtonElement;
    act(() => remove.click());
    expect(onChange).toHaveBeenCalledWith(['/b/two.txt']);
  });

  it('highlights the area while a file drag is over it and clears the highlight on drop', () => {
    act(() => root.render(<AttachedFilesEditor paths={[]} onChange={vi.fn()} />));
    const zone = container.querySelector('.attachment-drop-zone') as HTMLElement;
    act(() => {
      zone.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).toContain('Drop files here');
    act(() => {
      zone.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).not.toContain('Drop files here');
  });

  it('unregisters the picked-files handler on unmount', () => {
    act(() => root.render(<AttachedFilesEditor paths={[]} onChange={vi.fn()} />));
    expect(mocks.filesPickedHandler).not.toBeNull();
    act(() => root.unmount());
    expect(mocks.filesPickedHandler).toBeNull();
    root = createRoot(container);
  });
});

describe('AttachedFilesDisplay', () => {
  it('renders nothing for an empty list', () => {
    act(() => root.render(<AttachedFilesDisplay paths={[]} />));
    expect(container.innerHTML).toBe('');
  });

  it('shows the shared heading, opens a file from its name, reveals it, and offers no remove button', () => {
    act(() => root.render(<AttachedFilesDisplay paths={['/a/one.txt', '/b/two/']} />));
    expect(container.textContent).toContain('Attachments / References');
    const names = Array.from(container.querySelectorAll('.attachment-list__row-name')).map((node) => node.textContent);
    expect(names).toEqual(['one.txt', 'two']);
    const open = container.querySelector('.attachment-list__row-name.is-link') as HTMLButtonElement;
    act(() => open.click());
    expect(mocks.openFile).toHaveBeenCalledWith('/a/one.txt');
    const reveal = container.querySelector('[aria-label="Reveal one.txt in Finder"]') as HTMLButtonElement;
    act(() => reveal.click());
    expect(mocks.openContainingFolder).toHaveBeenCalledWith('/a/one.txt');
    expect(container.querySelector('.attachment-list__row-remove')).toBeNull();
  });
});
