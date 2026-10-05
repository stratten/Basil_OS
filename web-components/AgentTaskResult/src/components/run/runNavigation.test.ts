// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentRunOverviewStage } from './agentRunPresentation';
import {
  computeLocationRunId,
  findRunNavigationElement,
  flashNavigationTarget,
  navigationTargetForStage,
  prefersReducedMotion,
  resolveScrollLocationRunId,
  scrollOffsetForElement,
} from './runNavigation';

function stage(overrides: Partial<AgentRunOverviewStage>): AgentRunOverviewStage {
  return { id: 'overview:execution', kind: 'phase', label: 'Completing task', state: 'completed', startedAt: '', artifactCount: 0, ...overrides };
}

function mockTop(element: HTMLElement, top: number) {
  element.getBoundingClientRect = () => ({ top, bottom: top, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
}

function buildTranscript(): HTMLElement {
  const container = document.createElement('div');
  container.innerHTML = `
    <article data-run-content="root">
      <div data-run-anchor="root" id="root-anchor"></div>
      <div data-run-section="activity" id="root-activity"></div>
      <div data-interaction-entry-id="entry-1" id="root-entry"></div>
    </article>
    <div data-run-anchor="current" id="current-anchor"></div>
    <div data-run-section="activity" id="current-activity"></div>
    <div data-run-section="result" id="current-result"></div>
  `;
  return container;
}

describe('navigationTargetForStage', () => {
  it('maps phase, outcome, and interaction stages to their transcript targets', () => {
    expect(navigationTargetForStage(stage({ kind: 'phase' }))).toEqual({ kind: 'section', section: 'activity' });
    expect(navigationTargetForStage(stage({ kind: 'outcome', label: 'Run completed' }))).toEqual({ kind: 'section', section: 'result' });
    expect(navigationTargetForStage(stage({
      kind: 'interaction',
      interaction: { id: 'cp', entryId: 'entry-1', kind: 'clarification', status: 'answered', prompt: 'Which?', askedAt: '', responseHidden: false, options: [] },
    }))).toEqual({ kind: 'interaction', entryId: 'entry-1' });
  });

  it('treats an interaction stage without interaction data as an activity target', () => {
    expect(navigationTargetForStage(stage({ kind: 'interaction' }))).toEqual({ kind: 'section', section: 'activity' });
  });
});

describe('findRunNavigationElement', () => {
  it('finds prior-run targets inside that run card', () => {
    const container = buildTranscript();
    expect(findRunNavigationElement(container, { runId: 'root', target: { kind: 'section', section: 'activity' } }, true)?.id).toBe('root-activity');
    expect(findRunNavigationElement(container, { runId: 'root', target: { kind: 'interaction', entryId: 'entry-1' } }, true)?.id).toBe('root-entry');
  });

  it('ignores prior-run cards when resolving current-run targets', () => {
    const container = buildTranscript();
    expect(findRunNavigationElement(container, { runId: 'current', target: { kind: 'section', section: 'activity' } }, false)?.id).toBe('current-activity');
    expect(findRunNavigationElement(container, { runId: 'current', target: { kind: 'section', section: 'result' } }, false)?.id).toBe('current-result');
  });

  it('falls back to the turn anchor when the target is missing', () => {
    const container = buildTranscript();
    expect(findRunNavigationElement(container, { runId: 'current', target: { kind: 'interaction', entryId: 'entry-1' } }, false)?.id).toBe('current-anchor');
    expect(findRunNavigationElement(container, { runId: 'root', target: { kind: 'section', section: 'result' } }, true)?.id).toBe('root-anchor');
    expect(findRunNavigationElement(container, { runId: 'root', target: { kind: 'run' } }, true)?.id).toBe('root-anchor');
  });

  it('returns null when neither the target nor the anchor exists', () => {
    const container = buildTranscript();
    expect(findRunNavigationElement(container, { runId: 'missing', target: { kind: 'run' } }, true)).toBeNull();
  });

  it('matches run ids containing quotes and backslashes', () => {
    const container = document.createElement('div');
    const anchor = document.createElement('div');
    anchor.setAttribute('data-run-anchor', 'run"with\\chars');
    container.appendChild(anchor);
    expect(findRunNavigationElement(container, { runId: 'run"with\\chars', target: { kind: 'run' } }, false)).toBe(anchor);
  });
});

describe('computeLocationRunId', () => {
  function buildAnchors(tops: number[]): HTMLElement {
    const container = document.createElement('div');
    Object.defineProperty(container, 'clientHeight', { configurable: true, value: 400 });
    mockTop(container, 0);
    tops.forEach((top, index) => {
      const anchor = document.createElement('div');
      anchor.dataset.runAnchor = `run-${index}`;
      mockTop(anchor, top);
      container.appendChild(anchor);
    });
    return container;
  }

  it('returns the last anchor at or above 35% of the viewport', () => {
    expect(computeLocationRunId(buildAnchors([0, 120, 300]), 'fallback')).toBe('run-1');
    expect(computeLocationRunId(buildAnchors([0, 140, 300]), 'fallback')).toBe('run-1');
    expect(computeLocationRunId(buildAnchors([0, 160, 300]), 'fallback')).toBe('run-0');
  });

  it('uses the first anchor when every anchor is below the threshold', () => {
    expect(computeLocationRunId(buildAnchors([200, 300]), 'fallback')).toBe('run-0');
  });

  it('returns the fallback when no anchors exist', () => {
    expect(computeLocationRunId(buildAnchors([]), 'fallback')).toBe('fallback');
  });
});

describe('resolveScrollLocationRunId', () => {
  function buildScroller(scrollTop: number, scrollHeight: number, tops: number[]): HTMLElement {
    const container = document.createElement('div');
    Object.defineProperty(container, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(container, 'scrollHeight', { configurable: true, value: scrollHeight });
    Object.defineProperty(container, 'scrollTop', { configurable: true, value: scrollTop });
    mockTop(container, 0);
    tops.forEach((top, index) => {
      const anchor = document.createElement('div');
      anchor.dataset.runAnchor = `run-${index}`;
      mockTop(anchor, top);
      container.appendChild(anchor);
    });
    return container;
  }

  it('treats the top edge of a scrollable transcript as the first turn', () => {
    expect(resolveScrollLocationRunId(buildScroller(0, 2000, [0, 60, 120]), 'current', false)).toBe('run-0');
  });

  it('treats the bottom edge as the current turn', () => {
    expect(resolveScrollLocationRunId(buildScroller(1600, 2000, [-900, -500, 100]), 'current', true)).toBe('current');
  });

  it('measures the threshold between the edges', () => {
    expect(resolveScrollLocationRunId(buildScroller(500, 2000, [-300, 100, 300]), 'current', false)).toBe('run-1');
  });

  it('uses the current turn when the transcript does not scroll or has no turn labels', () => {
    expect(resolveScrollLocationRunId(buildScroller(0, 400, [0, 60]), 'current', true)).toBe('current');
    expect(resolveScrollLocationRunId(buildScroller(0, 2000, []), 'current', false)).toBe('current');
  });
});

describe('scrollOffsetForElement', () => {
  it('converts an element position into a container scroll offset with a top inset', () => {
    const container = document.createElement('div');
    const element = document.createElement('div');
    mockTop(container, 100);
    mockTop(element, 200);
    Object.defineProperty(container, 'scrollTop', { configurable: true, value: 200 });
    expect(scrollOffsetForElement(container, element)).toBe(292);
  });

  it('never returns a negative offset', () => {
    const container = document.createElement('div');
    const element = document.createElement('div');
    mockTop(container, 100);
    mockTop(element, 98);
    expect(scrollOffsetForElement(container, element)).toBe(0);
  });
});

describe('prefersReducedMotion', () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: originalMatchMedia });
  });

  it('reads the reduced-motion media query', () => {
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: vi.fn(() => ({ matches: true })) });
    expect(prefersReducedMotion()).toBe(true);
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: vi.fn(() => ({ matches: false })) });
    expect(prefersReducedMotion()).toBe(false);
  });

  it('returns false when matchMedia is unavailable', () => {
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: undefined });
    expect(prefersReducedMotion()).toBe(false);
  });
});

describe('flashNavigationTarget', () => {
  it('marks the element until its animation ends', () => {
    const element = document.createElement('div');
    flashNavigationTarget(element);
    expect(element.hasAttribute('data-navigation-flash')).toBe(true);
    element.dispatchEvent(new Event('animationend'));
    expect(element.hasAttribute('data-navigation-flash')).toBe(false);
  });
});
