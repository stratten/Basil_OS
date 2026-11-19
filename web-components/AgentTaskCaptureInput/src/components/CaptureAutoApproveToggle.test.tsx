// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { baseTextSnapshot, baseVoiceSnapshot } from '../fixtures/captureFixtures';
import type { CaptureSnapshot } from '../types';

const mocks = vi.hoisted(() => ({ setTaskAutoApprove: vi.fn() }));

vi.mock('../services/bridge', () => ({ setTaskAutoApprove: mocks.setTaskAutoApprove }));

import CaptureAutoApproveToggle from './CaptureAutoApproveToggle';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  mocks.setTaskAutoApprove.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(snapshot: CaptureSnapshot, compact = false) {
  act(() => {
    root.render(<CaptureAutoApproveToggle snapshot={snapshot} compact={compact} />);
  });
}

function toggle(): HTMLButtonElement {
  const element = container.querySelector<HTMLButtonElement>('button[role="switch"]');
  if (!element) throw new Error('Expected the switch.');
  return element;
}

describe('CaptureAutoApproveToggle', () => {
  it('shows off until native reports it on', () => {
    render(baseTextSnapshot());
    expect(toggle().getAttribute('aria-checked')).toBe('false');

    render(baseTextSnapshot({ taskAutoApproveEnabled: true }));
    expect(toggle().getAttribute('aria-checked')).toBe('true');
  });

  it('only asks native to change it, and shows no change until the next snapshot', () => {
    render(baseTextSnapshot());

    act(() => toggle().click());

    expect(mocks.setTaskAutoApprove).toHaveBeenCalledWith(true);
    expect(toggle().getAttribute('aria-checked')).toBe('false');
  });

  it('asks native to turn it off when it is on', () => {
    render(baseTextSnapshot({ taskAutoApproveEnabled: true }));

    act(() => toggle().click());

    expect(mocks.setTaskAutoApprove).toHaveBeenCalledWith(false);
  });

  it('is busy while native waits on the user, and cannot be clicked again', () => {
    render(baseTextSnapshot({ taskAutoApprovePending: true }));

    expect(toggle().getAttribute('aria-busy')).toBe('true');
    expect(toggle().disabled).toBe(true);
    act(() => toggle().click());
    expect(mocks.setTaskAutoApprove).not.toHaveBeenCalled();
  });

  it('shows why a change failed', () => {
    render(baseTextSnapshot({ taskAutoApproveError: 'Auto-approve could not be changed.' }));

    expect(toggle().title).toBe('Auto-approve could not be changed.');
  });

  it('cannot be changed once the request is being submitted or the capture is done', () => {
    render(baseTextSnapshot({ isSubmittingTextPrompt: true }));
    expect(toggle().disabled).toBe(true);

    render(baseVoiceSnapshot({ hasCompleted: true }));
    expect(toggle().disabled).toBe(true);
  });

  it('draws only the switch in the narrow voice window', () => {
    render(baseVoiceSnapshot(), true);

    expect(toggle().classList.contains('task-auto-approve-toggle--compact')).toBe(true);
  });
});
