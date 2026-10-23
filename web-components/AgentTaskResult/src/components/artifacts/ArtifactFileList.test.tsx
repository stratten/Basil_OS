// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';

import { ArtifactFileList } from './ArtifactFileList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ROW_STRIDE = 30;
const ROW_HEIGHT = 24;

function artifact(index: number): DerivedAgentTaskArtifact {
  return {
    artifactId: `file-${index}`,
    displayName: `doc-${index}.md`,
    localPath: `/tmp/doc-${index}.md`,
    lastTouchedAt: `2026-08-09T${String(10 + index).padStart(2, '0')}:00:00Z`,
    artifactKind: 'file',
    operation: 'create',
    lifecycle: 'verified',
    preview: { capability: 'unknown' },
    verification: { status: 'verified' },
    group: 'produced',
    review: { revision: null, revisionCount: index === 0 ? 2 : 0, kind: 'markdown', snapshotStatus: 'unavailable' },
  };
}

let container: HTMLDivElement;
let root: Root;
let contentHeight = 0;
let scrollTop = 0;

function render(total: number, activeIndex: number, onSelect = vi.fn()) {
  contentHeight = (total - 1) * ROW_STRIDE + ROW_HEIGHT;
  act(() => {
    root.render(
      <ArtifactFileList
        artifacts={Array.from({ length: total }, (_, index) => artifact(index))}
        activeArtifactId={`file-${activeIndex}`}
        onSelectArtifact={onSelect}
      />,
    );
  });
  return onSelect;
}

const tabs = () => Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
const sortButton = (label: string) => Array.from(container.querySelectorAll<HTMLButtonElement>('.artifact-file-list__sort-button'))
  .find(button => button.textContent?.startsWith(label))!;
const tabNames = () => tabs().map(tab => tab.textContent?.match(/doc-\d+\.md/)?.[0]);
const toggle = () => container.querySelector<HTMLButtonElement>('.basil-expandable-list__toggle');

beforeEach(() => {
  scrollTop = 0;
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  });
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function mockRect(this: Element) {
    const match = /doc-(\d+)\.md/.exec(this.textContent ?? '');
    const isTab = this.getAttribute('role') === 'tab' && match;
    const top = isTab ? Number(match[1]) * ROW_STRIDE : 0;
    const bottom = isTab ? top + ROW_HEIGHT : contentHeight;
    return { top, bottom, left: 0, right: 80, width: 80, height: bottom - top, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => contentHeight });
  Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value;
    },
  });
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

describe('ArtifactFileList', () => {
  it('keeps every row and the tablist semantics for a short list, with no toggle or fade', () => {
    render(2, 0);
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('Documents produced this turn');
    expect(container.querySelector('.artifact-file-list__title')?.textContent).toBe('Documents (2)');
    expect(tabs()).toHaveLength(2);
    expect(tabs()[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs()[0].textContent).toContain('v2');
    expect(toggle()).toBeNull();
    expect(container.querySelector('.is-fading')).toBeNull();
  });

  it('puts each document on its own row with a type icon and a modified label', () => {
    render(3, 0);
    expect(tabs()[0].querySelector('.file-type-icon--markdown')).not.toBeNull();
    expect(tabs()[0].querySelector('.artifact-file-row__icon')?.getAttribute('title')).toBe('Markdown');
    expect(tabs()[0].querySelector('.artifact-file-row__time')?.textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2} (am|pm)$/);
  });

  it('keeps the end of a long name visible while the start can truncate', () => {
    act(() => {
      root.render(
        <ArtifactFileList
          artifacts={[{ ...artifact(0), displayName: 'network_monitor_launcher_v2.sh' }]}
          activeArtifactId="file-0"
          onSelectArtifact={vi.fn()}
        />,
      );
    });
    const head = container.querySelector('.artifact-file-row__name-head')?.textContent ?? '';
    const tail = container.querySelector('.artifact-file-row__name-tail')?.textContent ?? '';
    expect(tail).toHaveLength(10);
    expect(head + tail).toBe('network_monitor_launcher_v2.sh');
  });

  it('collapses a long list to two faded rows and hides the rows beyond them from interaction', () => {
    render(20, 0);
    expect(toggle()?.textContent).toBe('Show all 20 documents');
    expect(container.querySelector('.basil-expandable-list__frame')?.classList.contains('is-fading')).toBe(true);
    expect(tabs().map(tab => tab.hasAttribute('inert')).slice(0, 6)).toEqual([
      false, false, true, true, true, true,
    ]);
    expect(tabs().slice(2).every(tab => tab.hasAttribute('inert'))).toBe(true);
  });

  it('scrolls to keep the active row visible when it sits beyond the collapsed rows', () => {
    render(20, 17);
    expect(tabs()[17].hasAttribute('inert')).toBe(false);
    expect(tabs()[0].hasAttribute('inert')).toBe(true);
    expect(scrollTop).toBeGreaterThan(0);
  });

  it('selects a document from a row and expands to reveal them all', () => {
    const onSelect = render(20, 0);
    act(() => {
      tabs()[3].click();
    });
    expect(onSelect).toHaveBeenCalledWith('file-3');
    act(() => {
      toggle()!.click();
    });
    expect(toggle()?.textContent).toBe('Show fewer');
    expect(tabs().every(tab => !tab.hasAttribute('inert'))).toBe(true);
  });

  it('shows no sort control for a single document', () => {
    render(1, 0);
    expect(container.querySelector('.artifact-file-list__sort')).toBeNull();
  });

  it('keeps the run order until a sort is chosen, then sorts, reverses, and returns to run order', () => {
    render(6, 0);
    expect(tabNames()).toEqual(['doc-0.md', 'doc-1.md', 'doc-2.md', 'doc-3.md', 'doc-4.md', 'doc-5.md']);

    act(() => sortButton('Name').click());
    expect(tabNames()[0]).toBe('doc-0.md');
    expect(sortButton('Name').getAttribute('aria-pressed')).toBe('true');

    act(() => sortButton('Name').click());
    expect(tabNames()[0]).toBe('doc-5.md');

    act(() => sortButton('Name').click());
    expect(tabNames()[0]).toBe('doc-0.md');
    expect(sortButton('Name').getAttribute('aria-pressed')).toBe('false');
  });

  it('sorts by modified time newest first and keeps the open document selected', () => {
    render(6, 2);
    act(() => sortButton('Modified').click());
    expect(tabNames()[0]).toBe('doc-5.md');
    const selected = tabs().find(tab => tab.getAttribute('aria-selected') === 'true');
    expect(selected?.textContent).toContain('doc-2.md');
  });
});
