// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installBasilTooltips, TOOLTIP_ELEMENT_ID, TOOLTIP_SHOW_DELAY_MS } from './basilTooltip';
import { computeTooltipPosition } from './tooltipPosition';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let dispose: () => void;

function mount(html: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  document.body.appendChild(host);
  return host;
}

function hover(element: Element, from: Element | null = null): void {
  element.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: from }));
}

function leave(element: Element, to: Element | null = null): void {
  element.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: to }));
}

function visibleTooltipText(): string | null {
  const tooltip = document.getElementById(TOOLTIP_ELEMENT_ID);
  return tooltip?.classList.contains('is-visible') ? tooltip.textContent : null;
}

function markTruncated(element: HTMLElement): void {
  element.style.overflow = 'hidden';
  Object.defineProperty(element, 'scrollWidth', { configurable: true, value: 200 });
  Object.defineProperty(element, 'clientWidth', { configurable: true, value: 100 });
}

describe('installBasilTooltips', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    dispose = installBasilTooltips();
  });

  afterEach(() => {
    dispose();
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  it('shows explicit text only after the half-second delay and links it for assistive technology', () => {
    const button = mount('<button type="button" data-tooltip="Open the run overview">Run</button>').querySelector('button')!;
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS - 1);
    expect(visibleTooltipText()).toBeNull();
    vi.advanceTimersByTime(1);
    expect(visibleTooltipText()).toBe('Open the run overview');
    expect(document.getElementById(TOOLTIP_ELEMENT_ID)?.getAttribute('role')).toBe('tooltip');
    expect(button.getAttribute('aria-describedby')).toBe(TOOLTIP_ELEMENT_ID);
    leave(button);
    expect(visibleTooltipText()).toBeNull();
    expect(button.hasAttribute('aria-describedby')).toBe(false);
  });

  it('replaces the native title tooltip during hover and restores the title afterwards', () => {
    const button = mount('<button type="button" title="Refresh preview"><svg></svg></button>').querySelector('button')!;
    hover(button);
    expect(button.hasAttribute('title')).toBe(false);
    expect(button.getAttribute('aria-label')).toBe('Refresh preview');
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Refresh preview');
    leave(button);
    expect(button.getAttribute('title')).toBe('Refresh preview');
    expect(button.hasAttribute('aria-label')).toBe(false);
  });

  it('skips a title that repeats fully visible text until that text is truncated', () => {
    const label = mount('<span title="Quarterly plan.pdf">Quarterly plan.pdf</span>').querySelector('span')!;
    hover(label);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBeNull();
    leave(label);
    markTruncated(label);
    hover(label);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Quarterly plan.pdf');
  });

  it('shows truncation-only explicit text only when a descendant is clipped', () => {
    const host = mount('<button type="button" data-tooltip="Quarterly plan final.pdf" data-tooltip-when="truncated"><span>Quarterly plan final.pdf</span></button>');
    const button = host.querySelector('button')!;
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBeNull();
    leave(button);
    markTruncated(host.querySelector('span')!);
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Quarterly plan final.pdf');
  });

  it('hides on press and keeps the native title suppressed until the pointer leaves', () => {
    const host = mount('<button type="button" title="Copy the answer"><svg></svg></button><p>elsewhere</p>');
    const button = host.querySelector('button')!;
    const paragraph = host.querySelector('p')!;
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    button.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    expect(visibleTooltipText()).toBeNull();
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS * 2);
    expect(visibleTooltipText()).toBeNull();
    expect(button.hasAttribute('title')).toBe(false);
    leave(button, paragraph);
    expect(button.getAttribute('title')).toBe('Copy the answer');
    hover(button, paragraph);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Copy the answer');
  });

  it('hides on Escape', () => {
    const button = mount('<button type="button" data-tooltip="Open task">Go</button>').querySelector('button')!;
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(visibleTooltipText()).toBeNull();
  });

  it('shows on keyboard focus without removing the title and hides on blur', () => {
    const button = mount('<button type="button" title="Start recording"><svg></svg></button>').querySelector('button')!;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    button.focus();
    expect(button.getAttribute('title')).toBe('Start recording');
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Start recording');
    button.blur();
    expect(visibleTooltipText()).toBeNull();
  });

  it('follows React title changes made during hover and does not restore a removed title', async () => {
    function Harness({ title }: { title?: string }) {
      return <button type="button" title={title}>Go</button>;
    }
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<Harness title="Send the draft" />));
    const button = host.querySelector('button')!;
    hover(button);
    await act(async () => root.render(<Harness title="Send the revised draft" />));
    expect(button.hasAttribute('title')).toBe(false);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Send the revised draft');
    await act(async () => root.render(<Harness />));
    leave(button);
    expect(button.hasAttribute('title')).toBe(false);
    act(() => root.unmount());
  });

  it('suppresses titled ancestors while a nested target is hovered', () => {
    const host = mount('<ul><li title="Workspace: Launch plan"><span>Launch plan</span><span class="flag" title="Needs attention">!</span></li></ul>');
    const item = host.querySelector('li')!;
    const flag = host.querySelector('.flag')!;
    hover(flag);
    expect(item.hasAttribute('title')).toBe(false);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBe('Needs attention');
    leave(flag);
    expect(item.getAttribute('title')).toBe('Workspace: Launch plan');
    expect(flag.getAttribute('title')).toBe('Needs attention');
  });

  it('ignores iframe titles', () => {
    const frame = mount('<iframe title="Live preview"></iframe>').querySelector('iframe')!;
    hover(frame);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(visibleTooltipText()).toBeNull();
    expect(frame.getAttribute('title')).toBe('Live preview');
  });

  it('hides when a container holding the target scrolls but not when an unrelated one does', () => {
    const host = mount('<div class="scroller"><button type="button" data-tooltip="Open task">Go</button></div><div class="other"></div>');
    hover(host.querySelector('button')!);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    host.querySelector('.other')!.dispatchEvent(new Event('scroll'));
    expect(visibleTooltipText()).toBe('Open task');
    host.querySelector('.scroller')!.dispatchEvent(new Event('scroll'));
    expect(visibleTooltipText()).toBeNull();
  });

  it('centers on small targets but follows the pointer on wide rows and tall blocks', () => {
    const host = mount('<button type="button" data-tooltip="Copy">C</button><div class="row" data-tooltip="Row hint">Row</div><div class="block" data-tooltip="Block hint">Block</div>');
    const setRect = (element: Element, rect: { top: number; left: number; width: number; height: number }) => {
      element.getBoundingClientRect = () => ({ ...rect, right: rect.left + rect.width, bottom: rect.top + rect.height, x: rect.left, y: rect.top, toJSON: () => rect }) as DOMRect;
    };
    const showAt = (element: Element, clientX: number, clientY: number) => {
      element.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, clientX, clientY }));
      element.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: clientX + 20, clientY }));
      vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
      const tooltip = document.getElementById(TOOLTIP_ELEMENT_ID)!;
      const position = { left: tooltip.style.left, top: tooltip.style.top };
      leave(element);
      return position;
    };
    const button = host.querySelector('button')!;
    const row = host.querySelector('.row')!;
    const block = host.querySelector('.block')!;
    setRect(button, { top: 100, left: 100, width: 40, height: 20 });
    setRect(row, { top: 200, left: 0, width: 600, height: 20 });
    setRect(block, { top: 300, left: 0, width: 600, height: 200 });

    expect(showAt(button, 105, 105)).toEqual({ left: '120px', top: '126px' });
    expect(showAt(row, 400, 205)).toEqual({ left: '420px', top: '226px' });
    expect(showAt(block, 300, 350)).toEqual({ left: '320px', top: '374px' });
  });

  it('installs once per document and stops after disposal', () => {
    expect(installBasilTooltips()).toBe(dispose);
    dispose();
    const button = mount('<button type="button" data-tooltip="Open task">Go</button>').querySelector('button')!;
    hover(button);
    vi.advanceTimersByTime(TOOLTIP_SHOW_DELAY_MS);
    expect(document.getElementById(TOOLTIP_ELEMENT_ID)).toBeNull();
  });
});

describe('computeTooltipPosition', () => {
  const viewport = { width: 400, height: 300 };

  it('centers below the anchor by default', () => {
    expect(computeTooltipPosition({ top: 100, left: 100, width: 40, height: 20 }, { width: 80, height: 24 }, viewport)).toEqual({ top: 126, left: 80, placement: 'below' });
  });

  it('flips above when there is no room below', () => {
    expect(computeTooltipPosition({ top: 270, left: 100, width: 40, height: 20 }, { width: 80, height: 24 }, viewport)).toEqual({ top: 240, left: 80, placement: 'above' });
  });

  it('clamps horizontally inside the viewport margin', () => {
    expect(computeTooltipPosition({ top: 100, left: 0, width: 20, height: 20 }, { width: 80, height: 24 }, viewport)).toEqual({ top: 126, left: 10, placement: 'below' });
    expect(computeTooltipPosition({ top: 100, left: 100, width: 40, height: 20 }, { width: 500, height: 24 }, viewport)).toEqual({ top: 126, left: 10, placement: 'below' });
  });

  it('honors left placement and falls back to right, then below', () => {
    const size = { width: 100, height: 30 };
    expect(computeTooltipPosition({ top: 100, left: 300, width: 20, height: 20 }, size, viewport, 'left')).toEqual({ top: 95, left: 194, placement: 'left' });
    expect(computeTooltipPosition({ top: 100, left: 20, width: 20, height: 20 }, size, viewport, 'left')).toEqual({ top: 95, left: 46, placement: 'right' });
    expect(computeTooltipPosition({ top: 100, left: 10, width: 100, height: 20 }, size, { width: 120, height: 300 }, 'left')).toEqual({ top: 126, left: 10, placement: 'below' });
  });

  it('rounds to whole pixels', () => {
    expect(computeTooltipPosition({ top: 100.4, left: 100.4, width: 40, height: 20 }, { width: 80, height: 24 }, viewport)).toEqual({ top: 126, left: 80, placement: 'below' });
  });
});
