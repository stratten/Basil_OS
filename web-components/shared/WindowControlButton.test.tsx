// @vitest-environment jsdom

import { act } from 'react';
import type { ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WindowControlButton } from './WindowControlButton';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('WindowControlButton', () => {
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

  function render(element: ReactElement) {
    act(() => {
      root.render(element);
    });
  }

  function button(): HTMLButtonElement {
    return container.querySelector<HTMLButtonElement>('button')!;
  }

  it('renders a labeled button with a decorative svg and a circle for every kind', () => {
    for (const kind of ['close', 'minimize', 'collapse'] as const) {
      render(<WindowControlButton kind={kind} label={`${kind} label`} onClick={vi.fn()} />);
      expect(button().type).toBe('button');
      expect(button().getAttribute('aria-label')).toBe(`${kind} label`);
      expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
      expect(container.querySelectorAll('circle.basil-window-control-circle')).toHaveLength(1);
    }
  });

  it('draws the cross for close, the dash for minimize, and the chevron only for collapse', () => {
    render(<WindowControlButton kind="close" label="Close" onClick={vi.fn()} />);
    expect(container.querySelectorAll('line')).toHaveLength(2);
    expect(container.querySelector('path')).toBeNull();
    render(<WindowControlButton kind="minimize" label="Minimize" onClick={vi.fn()} />);
    expect(container.querySelectorAll('line')).toHaveLength(1);
    expect(container.querySelector('path')).toBeNull();
    render(<WindowControlButton kind="collapse" label="Collapse" onClick={vi.fn()} />);
    expect(container.querySelectorAll('line')).toHaveLength(0);
    expect(container.querySelector('path.basil-window-control-chevron')).not.toBeNull();
  });

  it('calls the handler once with no arguments', () => {
    const onClick = vi.fn();
    render(<WindowControlButton kind="close" label="Close" onClick={onClick} />);
    act(() => button().click());
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith();
  });

  it('rotates the chevron through the is-collapsed class only while collapsed', () => {
    render(<WindowControlButton kind="collapse" label="Collapse" onClick={vi.fn()} />);
    expect(container.querySelector('path')?.getAttribute('class')).toBe('basil-window-control-chevron');
    render(<WindowControlButton kind="collapse" label="Expand" collapsed onClick={vi.fn()} />);
    expect(container.querySelector('path')?.getAttribute('class')).toBe('basil-window-control-chevron is-collapsed');
  });

  it('sets aria-pressed only when the host asks for it, including an explicit false', () => {
    render(<WindowControlButton kind="collapse" label="Collapse" onClick={vi.fn()} />);
    expect(button().hasAttribute('aria-pressed')).toBe(false);
    render(<WindowControlButton kind="collapse" label="Collapse" pressed={false} onClick={vi.fn()} />);
    expect(button().getAttribute('aria-pressed')).toBe('false');
    render(<WindowControlButton kind="collapse" label="Expand" pressed collapsed onClick={vi.fn()} />);
    expect(button().getAttribute('aria-pressed')).toBe('true');
  });

  it('passes the host button class through unchanged and adds none of its own', () => {
    render(<WindowControlButton kind="close" label="Close" className="host-btn host-btn--close" onClick={vi.fn()} />);
    expect(button().className).toBe('host-btn host-btn--close');
    render(<WindowControlButton kind="close" label="Close" onClick={vi.fn()} />);
    expect(button().hasAttribute('class')).toBe(false);
  });
});
