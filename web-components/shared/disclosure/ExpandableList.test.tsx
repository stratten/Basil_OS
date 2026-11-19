// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ExpandableList from './ExpandableList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let transitionDuration = '0.5s';
let contentScrollHeight = 400;
let frameHeight = 96;
let frameScrollTop = 0;
const scrollTopAssignments: number[] = [];

// Items are laid out from their data attributes: stacked rows of 16px with a 4px gap, or wrapped rows 30px apart.
function layoutFor(element: Element): { top: number; bottom: number } {
  const index = element.getAttribute('data-index');
  const row = element.getAttribute('data-row');
  if (row !== null) return { top: Number(row) * 30, bottom: Number(row) * 30 + 24 };
  if (index !== null) return { top: Number(index) * 20, bottom: Number(index) * 20 + 16 };
  return { top: 0, bottom: contentScrollHeight };
}

function renderCount(total: number, props: Partial<Parameters<typeof ExpandableList>[0]> = {}) {
  act(() => {
    root.render(
      <ExpandableList collapsedCount={5} {...props}>
        {Array.from({ length: total }, (_, index) => <div key={index} data-index={index}>Item {index}</div>)}
      </ExpandableList>,
    );
  });
}

function renderRows(rows: number[], props: Partial<Parameters<typeof ExpandableList>[0]> = {}) {
  act(() => {
    root.render(
      <ExpandableList collapsedRows={2} {...props}>
        {rows.map((row, index) => <div key={index} data-row={row}>Tab {index}</div>)}
      </ExpandableList>,
    );
  });
}

const frame = () => container.querySelector<HTMLDivElement>('.basil-expandable-list__frame')!;
const items = () => Array.from(container.querySelectorAll<HTMLElement>('.basil-expandable-list__content > div'));
const toggle = () => container.querySelector<HTMLButtonElement>('.basil-expandable-list__toggle');
const inertFlags = () => items().map(item => item.hasAttribute('inert'));

function endHeightTransition() {
  const event = new Event('transitionend', { bubbles: true });
  Object.assign(event, { propertyName: 'height' });
  act(() => {
    frame().dispatchEvent(event);
  });
}

beforeEach(() => {
  transitionDuration = '0.5s';
  contentScrollHeight = 400;
  frameHeight = 96;
  frameScrollTop = 0;
  scrollTopAssignments.length = 0;
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  });
  vi.spyOn(window, 'getComputedStyle').mockImplementation(
    () => ({ transitionDuration, transitionDelay: '0s' }) as unknown as CSSStyleDeclaration,
  );
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function mockRect(this: Element) {
    const { top, bottom } = layoutFor(this);
    return { top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => frameHeight });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => contentScrollHeight });
  Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
    configurable: true,
    get: () => frameScrollTop,
    set: (value: number) => {
      frameScrollTop = value;
      scrollTopAssignments.push(value);
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', { configurable: true, value: () => [{}] });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ExpandableList', () => {
  it('collapses to the first items, hides the rest from interaction, and offers to show all', () => {
    renderCount(8);
    expect(frame().classList.contains('is-collapsed')).toBe(true);
    expect(frame().style.getPropertyValue('--basil-expandable-list-collapsed-height')).toBe('96px');
    expect(inertFlags()).toEqual([false, false, false, false, false, true, true, true]);
    expect(toggle()?.textContent).toBe('Show all 8');
    expect(toggle()?.getAttribute('aria-expanded')).toBe('false');
    expect(toggle()?.getAttribute('aria-controls')).toBe(container.querySelector('.basil-expandable-list__content')?.id);
  });

  it('fades the collapsed window only when asked, only while items are hidden, and not once expanded', () => {
    renderCount(8);
    expect(frame().classList.contains('is-fading')).toBe(false);

    renderCount(8, { fadeCollapsed: true });
    expect(frame().classList.contains('is-fading')).toBe(true);

    renderCount(5, { fadeCollapsed: true });
    expect(frame().classList.contains('is-fading')).toBe(false);

    renderCount(8, { fadeCollapsed: true });
    act(() => {
      toggle()!.click();
    });
    expect(frame().classList.contains('is-fading')).toBe(false);
  });

  it('shows no toggle and hides nothing when the items fit', () => {
    renderCount(5);
    expect(toggle()).toBeNull();
    expect(frame().classList.contains('is-collapsed')).toBe(false);
    expect(inertFlags()).toEqual([false, false, false, false, false]);
  });

  it('animates open to the full height, lifts the hiding, and reads "Show fewer"', () => {
    renderCount(8);
    act(() => {
      toggle()!.click();
    });
    expect(toggle()?.textContent).toBe('Show fewer');
    expect(toggle()?.getAttribute('aria-expanded')).toBe('true');
    expect(frame().style.height).toBe('400px');
    expect(inertFlags().every(flag => !flag)).toBe(true);
    endHeightTransition();
    expect(frame().style.height).toBe('');
    expect(frame().classList.contains('is-collapsed')).toBe(false);
  });

  it('animates closed to the collapsed height and hides the tail again once settled', () => {
    renderCount(8);
    act(() => {
      toggle()!.click();
    });
    endHeightTransition();
    frameHeight = 400;
    act(() => {
      toggle()!.click();
    });
    expect(frame().style.height).toBe('96px');
    expect(inertFlags().every(flag => !flag)).toBe(true);
    endHeightTransition();
    expect(frame().classList.contains('is-collapsed')).toBe(true);
    expect(inertFlags()).toEqual([false, false, false, false, false, true, true, true]);
    expect(toggle()?.textContent).toBe('Show all 8');
  });

  it('settles at once under reduced motion', () => {
    transitionDuration = '0s';
    renderCount(8);
    act(() => {
      toggle()!.click();
    });
    expect(frame().style.height).toBe('');
    expect(toggle()?.textContent).toBe('Show fewer');
  });

  it('uses custom labels', () => {
    renderCount(7, { showAllLabel: total => `Show all ${total} files`, showFewerLabel: 'Show fewer files' });
    expect(toggle()?.textContent).toBe('Show all 7 files');
    act(() => {
      toggle()!.click();
    });
    expect(toggle()?.textContent).toBe('Show fewer files');
  });

  it('reports changes and follows the parent when controlled', () => {
    const onExpandedChange = vi.fn();
    renderCount(8, { expanded: false, onExpandedChange });
    act(() => {
      toggle()!.click();
    });
    expect(onExpandedChange).toHaveBeenCalledWith(true);
    expect(toggle()?.getAttribute('aria-expanded')).toBe('false');
    renderCount(8, { expanded: true, onExpandedChange });
    expect(toggle()?.getAttribute('aria-expanded')).toBe('true');
  });

  it('measures wrapped rows and only offers the toggle when rows are hidden', () => {
    contentScrollHeight = 114;
    renderRows([0, 0, 1, 1, 2, 2, 3]);
    expect(frame().style.getPropertyValue('--basil-expandable-list-collapsed-height')).toBe('54px');
    expect(inertFlags()).toEqual([false, false, false, false, true, true, true]);
    expect(toggle()?.textContent).toBe('Show all 7');
  });

  it('shows no toggle for wrapped items that already fit in the allowed rows', () => {
    contentScrollHeight = 54;
    renderRows([0, 0, 1, 1]);
    expect(toggle()).toBeNull();
    expect(inertFlags()).toEqual([false, false, false, false]);
  });

  it('scrolls the collapsed window so the kept item stays visible', () => {
    renderCount(8, { keepVisibleIndex: 7 });
    expect(frameScrollTop).toBe(60);
    expect(inertFlags()).toEqual([true, true, true, false, false, false, false, false]);
  });

  it('returns the scroll to the top when nothing needs keeping visible', () => {
    renderCount(8, { keepVisibleIndex: 7 });
    renderCount(8, { keepVisibleIndex: 1 });
    expect(frameScrollTop).toBe(0);
    expect(inertFlags()).toEqual([false, false, false, false, false, true, true, true]);
  });

  it('gives the content region the requested role and label', () => {
    renderCount(8, { contentRole: 'tablist', contentAriaLabel: 'Documents' });
    const content = container.querySelector('.basil-expandable-list__content')!;
    expect(content.getAttribute('role')).toBe('tablist');
    expect(content.getAttribute('aria-label')).toBe('Documents');
  });

  it('renders nothing hidden and no toggle for an empty list', () => {
    renderCount(0);
    expect(toggle()).toBeNull();
    expect(items()).toHaveLength(0);
  });
});
