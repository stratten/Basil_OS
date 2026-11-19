// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AttachmentArea from './AttachmentArea';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AttachmentArea', () => {
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

  const entries = [{ key: 'a', path: '/tmp/brief.pdf', removeLabel: 'Remove /tmp/brief.pdf' }];

  it('shows the shared heading, the Add button and the empty text when editable', () => {
    const onPick = vi.fn();
    act(() => root.render(<AttachmentArea entries={[]} canEdit onPick={onPick} />));
    expect(container.querySelector('h3')?.textContent).toBe('Attachments / References');
    expect(container.textContent).toContain('Nothing attached yet.');
    act(() => (container.querySelector('[aria-label="Attach files or folders"]') as HTMLButtonElement).click());
    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it('is read-only without an Add button, remove buttons or a drop highlight', () => {
    act(() => root.render(<AttachmentArea entries={entries} canEdit={false} onPick={vi.fn()} onRemove={vi.fn()} zoneTestId="zone" />));
    expect(container.querySelector('[aria-label="Attach files or folders"]')).toBeNull();
    expect(container.querySelector('.attachment-list__row-remove')).toBeNull();
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    act(() => {
      zone.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    expect(container.querySelector('.attachment-drop-overlay')).toBeNull();
  });

  it('shows the read-only empty text when nothing is attached and editing is off', () => {
    act(() => root.render(<AttachmentArea entries={[]} canEdit={false} onPick={vi.fn()} />));
    expect(container.textContent).toContain('Nothing is attached.');
  });

  it('lists entries with remove buttons, disables everything while busy, and shows the error', () => {
    const onRemove = vi.fn();
    act(() => root.render(<AttachmentArea entries={entries} canEdit onPick={vi.fn()} onRemove={onRemove} error="Could not attach." />));
    act(() => (container.querySelector('[aria-label="Remove /tmp/brief.pdf"]') as HTMLButtonElement).click());
    expect(onRemove).toHaveBeenCalledWith(entries[0], 0);
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not attach.');
    act(() => root.render(<AttachmentArea entries={entries} canEdit busy onPick={vi.fn()} onRemove={onRemove} />));
    expect((container.querySelector('[aria-label="Attach files or folders"]') as HTMLButtonElement).disabled).toBe(true);
    expect((container.querySelector('[aria-label="Remove /tmp/brief.pdf"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('arms through onArm while an editable drag is over the zone', () => {
    const onArm = vi.fn();
    act(() => root.render(<AttachmentArea entries={[]} canEdit onPick={vi.fn()} onArm={onArm} zoneTestId="zone" />));
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    act(() => {
      zone.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    expect(onArm).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('Drop files here');
  });
});
