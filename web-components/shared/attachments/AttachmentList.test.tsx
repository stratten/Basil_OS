// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AttachmentList from './AttachmentList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AttachmentList', () => {
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

  const entries = [
    { key: 'a', path: '/tmp/brief.pdf' },
    { key: 'b', path: '/tmp/project/', pending: true },
  ];

  it('renders nothing for an empty list', () => {
    act(() => root.render(<AttachmentList entries={[]} />));
    expect(container.innerHTML).toBe('');
  });

  it('shows the shared heading, basenames with path tooltips, and marks pending rows', () => {
    act(() => root.render(<AttachmentList entries={entries} />));
    expect(container.textContent).toContain('Attachments / References');
    const names = Array.from(container.querySelectorAll('.attachment-list__row-name'));
    expect(names.map((node) => node.textContent)).toEqual(['brief.pdf', 'project']);
    expect(names[0].getAttribute('title')).toBe('/tmp/brief.pdf');
    expect(container.querySelectorAll('.attachment-list__row.is-pending')).toHaveLength(1);
  });

  it('hides the heading on request and adds modifier classes', () => {
    act(() => root.render(<AttachmentList entries={entries} showHeading={false} className="attachment-list--inset" />));
    expect(container.querySelector('.attachment-list__header')).toBeNull();
    expect(container.querySelector('.attachment-list.attachment-list--inset')).not.toBeNull();
  });

  it('omits remove, open and reveal controls unless a handler is given', () => {
    act(() => root.render(<AttachmentList entries={entries} />));
    expect(container.querySelector('button')).toBeNull();
  });

  it('calls onRemove with the entry and its index, and honors removeDisabled and custom labels', () => {
    const onRemove = vi.fn();
    const labeled = [{ key: 'a', path: '/tmp/brief.pdf', removeLabel: 'Remove /tmp/brief.pdf' }];
    act(() => root.render(<AttachmentList entries={labeled} onRemove={onRemove} />));
    const button = container.querySelector('[aria-label="Remove /tmp/brief.pdf"]') as HTMLButtonElement;
    act(() => button.click());
    expect(onRemove).toHaveBeenCalledWith(labeled[0], 0);
    act(() => root.render(<AttachmentList entries={labeled} onRemove={onRemove} removeDisabled />));
    expect((container.querySelector('[aria-label="Remove /tmp/brief.pdf"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('makes names open buttons and adds a reveal button only when handlers are supplied', () => {
    const onOpen = vi.fn();
    const onReveal = vi.fn();
    act(() => root.render(<AttachmentList entries={entries.slice(0, 1)} onOpen={onOpen} onReveal={onReveal} />));
    act(() => (container.querySelector('.attachment-list__row-name.is-link') as HTMLButtonElement).click());
    act(() => (container.querySelector('[aria-label="Reveal brief.pdf in Finder"]') as HTMLButtonElement).click());
    expect(onOpen).toHaveBeenCalledWith(entries[0]);
    expect(onReveal).toHaveBeenCalledWith(entries[0]);
  });
});
