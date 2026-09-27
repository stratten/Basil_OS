// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ThinkingSegment } from '../../types';
import { ThinkingSegments } from './ThinkingSections';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function makeSegments(count: number): ThinkingSegment[] {
  return Array.from({ length: count }, (_, i) => ({
    iteration: i + 1,
    text: `Reasoning text for step ${i + 1}`,
    isComplete: true,
  }));
}

describe('ThinkingSegments single-segment rendering (unchanged behavior)', () => {
  it('renders the single segment as a standalone pill with no group toggle', () => {
    const markup = renderToStaticMarkup(
      <ThinkingSegments segments={makeSegments(1)} isLive={false} collapseForResponse={false} />
    );

    expect(markup).toContain('thinking-pill');
    expect(markup).not.toContain('thinking-history-group');
    expect(markup).not.toContain('Reasoning (Step');
    expect(markup).toContain('Reasoning text for step 1');
  });
});

describe('ThinkingSegments grouped reasoning history', () => {
  it('shows only the latest standalone pill plus one group toggle for 6 segments', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <ThinkingSegments segments={makeSegments(6)} isLive={false} collapseForResponse={false} />
        );
      });

      // Only the latest segment (Step 6) renders its own standalone header;
      // the other 5 are hidden behind the group toggle until expanded.
      const standaloneHeaders = Array.from(
        container.querySelectorAll('.thinking-segments > .thinking-pill > .execution-steps-header')
      );
      expect(standaloneHeaders.length).toBe(1);
      expect(standaloneHeaders[0].textContent).toContain('Reasoning (Step 6)');

      const groupToggle = container.querySelector('.thinking-history-group > .execution-steps-header');
      expect(groupToggle).not.toBeNull();
      expect(groupToggle?.textContent).toContain('5 earlier reasoning steps');

      // The 5 earlier pills exist in the DOM (for smooth collapse
      // animation) but are not shown as their own top-level headers.
      const groupedPills = container.querySelectorAll('.thinking-history-group .thinking-pill');
      expect(groupedPills.length).toBe(5);
    } finally {
      act(() => root.unmount());
    }
  });

  it('reveals the earlier steps when the group toggle is clicked', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <ThinkingSegments segments={makeSegments(6)} isLive={false} collapseForResponse={false} />
        );
      });

      const groupToggle = container.querySelector<HTMLElement>('.thinking-history-group > .execution-steps-header');
      expect(container.querySelector('.thinking-history-group .thinking-collapse.expanded')).toBeNull();

      act(() => {
        groupToggle?.click();
      });

      expect(container.querySelector('.thinking-history-group .thinking-collapse.expanded')).not.toBeNull();
      for (let step = 1; step <= 5; step++) {
        expect(container.textContent).toContain(`Reasoning (Step ${step})`);
      }
    } finally {
      act(() => root.unmount());
    }
  });
});
