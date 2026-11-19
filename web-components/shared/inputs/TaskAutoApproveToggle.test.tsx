// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TaskAutoApproveToggle from './TaskAutoApproveToggle';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

function toggle(): HTMLButtonElement {
  const element = container.querySelector<HTMLButtonElement>('button[role="switch"]');
  if (!element) throw new Error('Expected the switch.');
  return element;
}

function render(props: Partial<React.ComponentProps<typeof TaskAutoApproveToggle>> = {}) {
  const onChange = vi.fn();
  act(() => {
    root.render(<TaskAutoApproveToggle enabled={false} onChange={onChange} {...props} />);
  });
  return onChange;
}

describe('TaskAutoApproveToggle', () => {
  it('is a labeled switch that reports off', () => {
    render();

    expect(toggle().getAttribute('aria-checked')).toBe('false');
    expect(toggle().textContent).toBe('Auto-approve');
    expect(toggle().classList.contains('is-on')).toBe(false);
  });

  it('reports on and is marked as a standing risk', () => {
    render({ enabled: true });

    expect(toggle().getAttribute('aria-checked')).toBe('true');
    expect(toggle().classList.contains('is-on')).toBe(true);
  });

  it('asks for the opposite state when clicked', () => {
    const turnedOn = render();
    act(() => toggle().click());
    expect(turnedOn).toHaveBeenCalledWith(true);

    const turnedOff = render({ enabled: true });
    act(() => toggle().click());
    expect(turnedOff).toHaveBeenCalledWith(false);
  });

  it('explains what it does, including what still asks, while off', () => {
    render();

    expect(toggle().title).toContain('without asking you first');
    expect(toggle().title).toContain('still ask');
  });

  it('says how to turn it off while on', () => {
    render({ enabled: true });

    expect(toggle().title).toContain('turn this off');
  });

  it('cannot be clicked again while a change is waiting on the user, and says it is busy', () => {
    const onChange = render({ pending: true });

    expect(toggle().disabled).toBe(true);
    expect(toggle().getAttribute('aria-busy')).toBe('true');
    expect(toggle().classList.contains('is-pending')).toBe(true);
    act(() => toggle().click());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('cannot be clicked while disabled', () => {
    const onChange = render({ disabled: true });

    expect(toggle().disabled).toBe(true);
    act(() => toggle().click());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('shows why a change failed as its tooltip and marks the failure', () => {
    render({ error: 'Basil is not running.' });

    expect(toggle().title).toBe('Basil is not running.');
    expect(toggle().classList.contains('has-error')).toBe(true);
  });

  it('keeps its label as the accessible name when compact', () => {
    render({ compact: true });

    expect(toggle().classList.contains('task-auto-approve-toggle--compact')).toBe(true);
    expect(toggle().textContent).toBe('Auto-approve');
  });
});
