// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AttachmentDropZone from './AttachmentDropZone';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AttachmentDropZone', () => {
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

  const fire = (target: Element, type: string) =>
    act(() => {
      target.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }));
    });

  it('shows the overlay and arms on every drag-over, then clears and disarms on leave', () => {
    const onArm = vi.fn();
    const onDisarm = vi.fn();
    act(() => root.render(<AttachmentDropZone data-testid="zone" onArm={onArm} onDisarm={onDisarm}><span>child</span></AttachmentDropZone>));
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    expect(container.querySelector('.attachment-drop-overlay')).toBeNull();
    fire(zone, 'dragenter');
    fire(zone, 'dragover');
    expect(onArm).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('Drop files here');
    expect(zone.classList.contains('is-drag-over')).toBe(true);
    fire(zone, 'dragleave');
    expect(container.querySelector('.attachment-drop-overlay')).toBeNull();
    expect(onDisarm).toHaveBeenCalledTimes(1);
  });

  it('clears the overlay on drop without reading dropped files', () => {
    const onDisarm = vi.fn();
    act(() => root.render(<AttachmentDropZone data-testid="zone" onDisarm={onDisarm}>x</AttachmentDropZone>));
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    fire(zone, 'dragover');
    expect(container.querySelector('.attachment-drop-overlay')).not.toBeNull();
    fire(zone, 'drop');
    expect(container.querySelector('.attachment-drop-overlay')).toBeNull();
    expect(onDisarm).toHaveBeenCalledTimes(1);
  });

  it('keeps the arm in place on drop when disarmOnDrop is false, but still disarms on leave', () => {
    const onDisarm = vi.fn();
    act(() => root.render(<AttachmentDropZone data-testid="zone" disarmOnDrop={false} onDisarm={onDisarm}>x</AttachmentDropZone>));
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    fire(zone, 'dragover');
    fire(zone, 'drop');
    expect(container.querySelector('.attachment-drop-overlay')).toBeNull();
    expect(onDisarm).not.toHaveBeenCalled();
    fire(zone, 'dragover');
    fire(zone, 'dragleave');
    expect(onDisarm).toHaveBeenCalledTimes(1);
  });

  it('swallows drags but never highlights or arms while disabled', () => {
    const onArm = vi.fn();
    act(() => root.render(<AttachmentDropZone data-testid="zone" disabled onArm={onArm}>x</AttachmentDropZone>));
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    const event = new Event('dragover', { bubbles: true, cancelable: true });
    act(() => {
      zone.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    expect(onArm).not.toHaveBeenCalled();
    expect(container.querySelector('.attachment-drop-overlay')).toBeNull();
  });

  it('forwards extra attributes and merges class names', () => {
    act(() => root.render(<AttachmentDropZone data-testid="zone" data-run-control-mode="running" className="host-class">x</AttachmentDropZone>));
    const zone = container.querySelector('[data-testid="zone"]') as HTMLElement;
    expect(zone.getAttribute('data-run-control-mode')).toBe('running');
    expect(zone.classList.contains('host-class')).toBe(true);
    expect(zone.classList.contains('attachment-drop-zone')).toBe(true);
  });
});
