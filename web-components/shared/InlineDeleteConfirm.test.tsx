// @vitest-environment jsdom

import { act } from 'react';
import type { ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InlineDeleteConfirm } from './InlineDeleteConfirm';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('InlineDeleteConfirm', () => {
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

  function buttons(): HTMLButtonElement[] {
    return Array.from(container.querySelectorAll<HTMLButtonElement>('.inline-delete-confirm__btn'));
  }

  it('renders the label with Cancel first and a danger Delete second', () => {
    render(<InlineDeleteConfirm label="Delete this task?" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(container.querySelector('.inline-delete-confirm__label')?.textContent).toBe('Delete this task?');
    const [cancel, confirm] = buttons();
    expect(cancel.textContent).toBe('Cancel');
    expect(confirm.textContent).toBe('Delete');
    expect(confirm.classList.contains('inline-delete-confirm__btn--danger')).toBe(true);
    expect(cancel.classList.contains('inline-delete-confirm__btn--danger')).toBe(false);
    expect(container.querySelector('.inline-delete-confirm__label')?.nextElementSibling).toBe(
      container.querySelector('.inline-delete-confirm__actions'),
    );
  });

  it('calls only the matching handler and stops click propagation to the host row', () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    const onRowClick = vi.fn();
    render(
      <div onClick={onRowClick}>
        <InlineDeleteConfirm label="Delete?" onCancel={onCancel} onConfirm={onConfirm} />
      </div>,
    );
    act(() => buttons()[0].click());
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    act(() => buttons()[1].click());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it('disables Delete and shows the busy label while busy, but keeps Cancel enabled', () => {
    const onConfirm = vi.fn();
    render(<InlineDeleteConfirm label="Delete?" busy onCancel={vi.fn()} onConfirm={onConfirm} />);
    const [cancel, confirm] = buttons();
    expect(confirm.disabled).toBe(true);
    expect(confirm.textContent).toBe('Deleting...');
    expect(cancel.disabled).toBe(false);
    act(() => confirm.click());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('honors custom button and busy labels', () => {
    render(
      <InlineDeleteConfirm
        label="Remove?"
        confirmLabel="Remove"
        cancelLabel="Keep"
        busy
        busyLabel="Removing..."
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    const [cancel, confirm] = buttons();
    expect(cancel.textContent).toBe('Keep');
    expect(confirm.textContent).toBe('Removing...');
  });

  it('is an alertdialog only when an accessible name is supplied', () => {
    render(<InlineDeleteConfirm label="Delete?" ariaLabel="Delete meeting" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    const named = container.querySelector('.inline-delete-confirm');
    expect(named?.getAttribute('role')).toBe('alertdialog');
    expect(named?.getAttribute('aria-label')).toBe('Delete meeting');
    render(<InlineDeleteConfirm label="Delete?" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    const anonymous = container.querySelector('.inline-delete-confirm');
    expect(anonymous?.hasAttribute('role')).toBe(false);
    expect(anonymous?.hasAttribute('aria-label')).toBe(false);
  });

  it('adds the stacked modifier and appends the host className without dropping the base class', () => {
    render(
      <InlineDeleteConfirm layout="stacked" className="host-row host-row--confirm" label="Delete?" onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    const stacked = container.querySelector('.inline-delete-confirm')!;
    expect(stacked.className).toBe('inline-delete-confirm inline-delete-confirm--stacked host-row host-row--confirm');
    render(<InlineDeleteConfirm label="Delete?" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(container.querySelector('.inline-delete-confirm')?.className).toBe('inline-delete-confirm');
  });

  it('keeps a very long label from breaking the row layout contract', () => {
    const longLabel = 'Delete this conversation about a very long title that cannot possibly fit on a single sidebar row?';
    render(<InlineDeleteConfirm label={longLabel} onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(container.querySelector('.inline-delete-confirm__label')?.textContent).toBe(longLabel);
    expect(buttons()).toHaveLength(2);
  });
});
