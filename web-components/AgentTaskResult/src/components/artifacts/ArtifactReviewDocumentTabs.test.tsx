// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';

vi.mock('../../services/api', () => ({
  listArtifactRevisions: vi.fn(),
  getArtifactRevision: vi.fn(),
  getBaseUrl: vi.fn(() => ''),
}));

vi.mock('./managedHistory/managedHistoryApi', () => ({
  listManagedFileVersions: vi.fn(),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));

import { ArtifactReviewDocumentTabs } from './ArtifactReviewWorkspace';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TABS_PER_ROW = 4;
const ROW_STRIDE = 30;
const ROW_HEIGHT = 24;

function artifact(index: number): DerivedAgentTaskArtifact {
  return {
    artifactId: `file-${index}`,
    displayName: `doc-${index}.md`,
    localPath: `/tmp/doc-${index}.md`,
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
  contentHeight = (Math.ceil(total / TABS_PER_ROW) - 1) * ROW_STRIDE + ROW_HEIGHT;
  act(() => {
    root.render(
      <ArtifactReviewDocumentTabs
        artifacts={Array.from({ length: total }, (_, index) => artifact(index))}
        activeArtifactId={`file-${activeIndex}`}
        onSelectArtifact={onSelect}
      />,
    );
  });
  return onSelect;
}

const tabs = () => Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
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
    const row = isTab ? Math.floor(Number(match[1]) / TABS_PER_ROW) : 0;
    const top = isTab ? row * ROW_STRIDE : 0;
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

describe('ArtifactReviewDocumentTabs', () => {
  it('keeps every tab and the tablist semantics for a short list, with no toggle', () => {
    render(6, 0);
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('Documents produced this turn');
    expect(tabs()).toHaveLength(6);
    expect(tabs()[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs()[0].textContent).toContain('v2');
    expect(toggle()).toBeNull();
  });

  it('collapses a long list to two rows and hides the tabs beyond them from interaction', () => {
    render(20, 0);
    expect(toggle()?.textContent).toBe('Show all 20 documents');
    expect(tabs().map(tab => tab.hasAttribute('inert')).slice(0, 10)).toEqual([
      false, false, false, false, false, false, false, false, true, true,
    ]);
    expect(tabs().slice(8).every(tab => tab.hasAttribute('inert'))).toBe(true);
  });

  it('scrolls to keep the active tab visible when it sits beyond the collapsed rows', () => {
    render(20, 17);
    expect(tabs()[17].hasAttribute('inert')).toBe(false);
    expect(tabs()[0].hasAttribute('inert')).toBe(true);
    expect(scrollTop).toBeGreaterThan(0);
  });

  it('selects a document from a tab and expands to reveal them all', () => {
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
});
