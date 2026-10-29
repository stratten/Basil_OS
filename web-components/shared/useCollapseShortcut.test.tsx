// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useCollapseShortcut } from './useCollapseShortcut';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Harness({ toggle, enabled = true }: { toggle: () => void; enabled?: boolean }) {
  useCollapseShortcut(toggle, enabled);
  return <input data-testid="field" />;
}

function press(init: KeyboardEventInit, target: EventTarget = document): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: 'e', bubbles: true, cancelable: true, ...init });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}

describe('useCollapseShortcut', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function render(toggle: () => void, enabled = true) {
    act(() => {
      root.render(<Harness toggle={toggle} enabled={enabled} />);
    });
  }

  it('calls the toggle once on Cmd+E and prevents the default', () => {
    const toggle = vi.fn();
    render(toggle);
    const event = press({ metaKey: true });
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it('matches an uppercase E from caps lock', () => {
    const toggle = vi.fn();
    render(toggle);
    press({ metaKey: true, key: 'E' });
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('ignores plain E, Ctrl+E, Option+Cmd+E and Shift+Cmd+E', () => {
    const toggle = vi.fn();
    render(toggle);
    press({});
    press({ ctrlKey: true });
    press({ metaKey: true, altKey: true });
    press({ metaKey: true, shiftKey: true });
    expect(toggle).not.toHaveBeenCalled();
  });

  it('ignores other Cmd chords', () => {
    const toggle = vi.fn();
    render(toggle);
    press({ metaKey: true, key: 'w' });
    expect(toggle).not.toHaveBeenCalled();
  });

  it('ignores key repeat and IME composition', () => {
    const toggle = vi.fn();
    render(toggle);
    press({ metaKey: true, repeat: true });
    press({ metaKey: true, isComposing: true });
    expect(toggle).not.toHaveBeenCalled();
  });

  it('does not register when disabled and registers when re-enabled', () => {
    const toggle = vi.fn();
    render(toggle, false);
    press({ metaKey: true });
    expect(toggle).not.toHaveBeenCalled();
    render(toggle, true);
    press({ metaKey: true });
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('ignores events another listener already handled', () => {
    const toggle = vi.fn();
    const earlier = (event: KeyboardEvent) => event.preventDefault();
    document.addEventListener('keydown', earlier);
    render(toggle);
    press({ metaKey: true });
    document.removeEventListener('keydown', earlier);
    expect(toggle).not.toHaveBeenCalled();
  });

  it('calls the newest toggle after a re-render', () => {
    const first = vi.fn();
    const second = vi.fn();
    render(first);
    render(second);
    press({ metaKey: true });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('still fires from a focused text input', () => {
    const toggle = vi.fn();
    render(toggle);
    const field = container.querySelector<HTMLInputElement>('[data-testid="field"]')!;
    field.focus();
    press({ metaKey: true }, field);
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('removes the listener on unmount', () => {
    const toggle = vi.fn();
    render(toggle);
    act(() => root.unmount());
    press({ metaKey: true });
    expect(toggle).not.toHaveBeenCalled();
    root = createRoot(container);
  });
});
