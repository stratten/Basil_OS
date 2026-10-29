// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import CaptureHeader from './CaptureHeader';
import type { CaptureInputMessage } from '../types';
import { baseTextSnapshot, baseVoiceSnapshot } from '../fixtures/captureFixtures';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
let postMessage: Mock<(message: CaptureInputMessage) => void>;

beforeEach(() => {
  postMessage = vi.fn<(message: CaptureInputMessage) => void>();
  window.webkit = { messageHandlers: { agentTaskCaptureBridge: { postMessage } } };
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(snapshot: ReturnType<typeof baseVoiceSnapshot>, isCollapsed = false, onToggleCollapse: () => void = () => undefined) {
  act(() => {
    root.render(<CaptureHeader snapshot={snapshot} displayName="Paprika" isCollapsed={isCollapsed} onToggleCollapse={onToggleCollapse} />);
  });
}

function click(label: string) {
  const button = container.querySelector(`[aria-label="${label}"]`) as HTMLButtonElement;
  expect(button).not.toBeNull();
  act(() => button.click());
}

describe('CaptureHeader', () => {
  it('dispatches cancellation from its leading control', () => {
    render(baseVoiceSnapshot());

    click('Cancel task');

    expect(postMessage).toHaveBeenCalledWith({ type: 'cancelCapture' });
  });

  it('reports the measured header extent to the native drag surface', () => {
    const geometrySpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('basil-webkit-window-frame')) return new DOMRect(0, 0, 160, 180);
      return new DOMRect(4, 4, 152, 24);
    });

    try {
      act(() => {
        root.render(
          <div className="basil-webkit-window-frame">
            <CaptureHeader snapshot={baseVoiceSnapshot()} displayName="Paprika" isCollapsed={false} onToggleCollapse={() => undefined} />
          </div>,
        );
      });

      expect(postMessage).toHaveBeenCalledWith({ type: 'captureHeaderExtent', height: 28 });
    } finally {
      geometrySpy.mockRestore();
    }
  });

  it('dispatches the history action from its trailing control', () => {
    render(baseVoiceSnapshot());

    click('Show task history');

    expect(postMessage).toHaveBeenCalledWith({ type: 'showHistory' });
  });

  it('switches from voice to text entry', () => {
    render(baseVoiceSnapshot());

    click('Switch to text entry');

    expect(postMessage).toHaveBeenCalledWith({ type: 'enterTextEntryMode' });
  });

  it('switches from text entry to voice capture', () => {
    render(baseTextSnapshot());

    click('Switch to voice capture');

    expect(postMessage).toHaveBeenCalledWith({ type: 'enterVoiceMode' });
  });

  it('offers collapse in text entry, to the right of the cancel control in the same row, at the same size as the cancel glyph', () => {
    const onToggle = vi.fn();
    render(baseTextSnapshot(), false, onToggle);

    const leading = container.querySelector('.capture-header__leading') as HTMLElement;
    const collapse = leading.querySelector('[aria-label="Collapse window"]') as HTMLButtonElement;
    expect(collapse).not.toBeNull();
    expect(collapse.className).toContain('capture-header__icon-button');
    expect(collapse.getAttribute('aria-pressed')).toBe('false');
    expect(leading.children[0]).toBe(leading.querySelector('[aria-label="Cancel task"]'));
    expect(leading.children[1]).toBe(collapse);
    expect(leading.classList.contains('capture-header__leading--row')).toBe(true);
    expect(leading.querySelector('.capture-header__leading-spacer')).toBeNull();

    act(() => collapse.click());
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(postMessage).not.toHaveBeenCalledWith({ type: 'cancelCapture' });
  });

  it('labels the control Expand window while collapsed and rotates the chevron', () => {
    render(baseTextSnapshot(), true);

    const expand = container.querySelector('[aria-label="Expand window"]') as HTMLButtonElement;
    expect(expand).not.toBeNull();
    expect(expand.getAttribute('aria-pressed')).toBe('true');
    expect(expand.querySelector('.basil-window-control-chevron.is-collapsed')).not.toBeNull();
    expect(container.querySelector('[aria-label="Collapse window"]')).toBeNull();
  });

  it('keeps the empty spacer in voice mode so the header height is unchanged, but never traps a collapsed window', () => {
    render(baseVoiceSnapshot());
    expect(container.querySelector('[aria-label="Collapse window"]')).toBeNull();
    expect((container.querySelector('.capture-header__leading') as HTMLElement).classList.contains('capture-header__leading--row')).toBe(false);
    expect(container.querySelector('.capture-header__leading-spacer')).not.toBeNull();

    render(baseVoiceSnapshot(), true);
    expect(container.querySelector('[aria-label="Expand window"]')).not.toBeNull();
  });
});
