// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ThinkingSegment } from '../../types';
import { ThinkingSegments, reasoningPassLabel } from './ThinkingSections';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('reasoningPassLabel', () => {
  it('names the final-answer and verifier passes instead of numbering them', () => {
    expect(reasoningPassLabel(3)).toBe('Reasoning (Step 3)');
    expect(reasoningPassLabel(-1)).toBe('Reasoning (Final answer)');
    expect(reasoningPassLabel(-2)).toBe('Reasoning (Verifying the outcome)');
  });

  it('labels a lone verifier segment by its pass', () => {
    const markup = renderToStaticMarkup(
      <ThinkingSegments
        segments={[{ iteration: -2, text: 'Checking the answer against the request', isComplete: true }]}
        isLive={false}
        collapseForResponse={false}
      />,
    );

    expect(markup).toContain('Reasoning (Verifying the outcome)');
  });
});

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
          <ThinkingSegments segments={makeSegments(6)} isLive={false} isRunActive collapseForResponse={false} />
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
      expect(groupToggle?.textContent).toContain('5 earlier reasoning passes');

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
          <ThinkingSegments segments={makeSegments(6)} isLive={false} isRunActive collapseForResponse={false} />
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

describe('ThinkingSegments after the run finishes', () => {
  it('folds every step, including the latest, into one group', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <ThinkingSegments segments={makeSegments(6)} isLive={false} isRunActive={false} collapseForResponse={false} />
        );
      });

      expect(container.querySelectorAll('.thinking-segments > .thinking-pill')).toHaveLength(0);
      const groupToggle = container.querySelector('.thinking-history-group > .execution-steps-header');
      expect(groupToggle?.textContent).toContain('6 reasoning passes');
      expect(groupToggle?.textContent).not.toContain('earlier');
      expect(container.querySelectorAll('.thinking-history-group .thinking-pill')).toHaveLength(6);
      expect(container.textContent).toContain('Reasoning (Step 6)');
    } finally {
      act(() => root.unmount());
    }
  });

  it('keeps the latest step separate while the run is active, then folds it in on completion', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <ThinkingSegments segments={makeSegments(3)} isLive={false} isRunActive collapseForResponse={false} />
        );
      });
      expect(container.querySelectorAll('.thinking-segments > .thinking-pill')).toHaveLength(1);

      act(() => {
        root.render(
          <ThinkingSegments segments={makeSegments(3)} isLive={false} isRunActive={false} collapseForResponse={false} />
        );
      });
      expect(container.querySelectorAll('.thinking-segments > .thinking-pill')).toHaveLength(0);
      expect(container.querySelector('.thinking-history-group > .execution-steps-header')?.textContent)
        .toContain('3 reasoning passes');
    } finally {
      act(() => root.unmount());
    }
  });

  it('leaves a single step as a standalone pill', () => {
    const markup = renderToStaticMarkup(
      <ThinkingSegments segments={makeSegments(1)} isLive={false} isRunActive={false} collapseForResponse={false} />
    );

    expect(markup).toContain('thinking-pill');
    expect(markup).not.toContain('thinking-history-group');
  });

  it('falls back to isLive when isRunActive is omitted', () => {
    const markup = renderToStaticMarkup(
      <ThinkingSegments segments={makeSegments(4)} isLive={false} collapseForResponse={false} />
    );

    expect(markup).toContain('4 reasoning passes');
  });
});

function withLatestComplete(count: number, latestComplete: boolean): ThinkingSegment[] {
  return makeSegments(count).map((seg, index) => (index === count - 1 ? { ...seg, isComplete: latestComplete } : seg));
}

function latestPill(container: HTMLElement): Element | undefined {
  const pills = container.querySelectorAll('.thinking-segments > .thinking-pill');
  return pills[pills.length - 1];
}

function latestPillExpanded(container: HTMLElement): boolean {
  return Boolean(latestPill(container)?.querySelector('.thinking-collapse')?.classList.contains('expanded'));
}

function clickLatestPill(container: HTMLElement) {
  const header = latestPill(container)?.querySelector('.execution-steps-header') as HTMLElement | null;
  act(() => header?.click());
}

describe('ThinkingSegments follows what the user is watching', () => {
  it('keeps a pass the user opened open when a new pass arrives', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(2)} isLive={false} isRunActive collapseForResponse={false} />);
      });
      expect(latestPillExpanded(container)).toBe(false);

      clickLatestPill(container);
      expect(latestPillExpanded(container)).toBe(true);

      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(3)} isLive={false} isRunActive collapseForResponse={false} />);
      });
      expect(latestPill(container)?.textContent).toContain('Reasoning (Step 3)');
      expect(latestPillExpanded(container)).toBe(true);
    } finally {
      act(() => root.unmount());
    }
  });

  it('hands the open view to the new pass and folds the one it replaces into the earlier passes', () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const expandedBodies = () => container.querySelectorAll('.thinking-pill .thinking-collapse.expanded');

    try {
      act(() => {
        root.render(<ThinkingSegments segments={withLatestComplete(2, false)} isLive isRunActive collapseForResponse={false} />);
      });
      clickLatestPill(container);
      expect(latestPill(container)?.textContent).toContain('Reasoning (Step 2)');
      expect(expandedBodies()).toHaveLength(1);

      act(() => {
        root.render(<ThinkingSegments segments={withLatestComplete(3, false)} isLive isRunActive collapseForResponse={false} />);
      });
      expect(latestPill(container)?.textContent).toContain('Reasoning (Step 3)');
      expect(latestPillExpanded(container)).toBe(true);
      expect(expandedBodies()).toHaveLength(1);
      expect(container.querySelector('.thinking-history-group')?.textContent).toContain('2 earlier reasoning passes');
      expect(container.querySelectorAll('.thinking-history-group .thinking-collapse.expanded')).toHaveLength(0);
    } finally {
      act(() => root.unmount());
    }
  });

  it('does not follow a pass the user opened from the earlier passes', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(3)} isLive={false} isRunActive collapseForResponse={false} />);
      });
      act(() => (container.querySelector('.thinking-history-group > .execution-steps-header') as HTMLElement).click());
      act(() => (container.querySelector('.thinking-history-group .thinking-pill .execution-steps-header') as HTMLElement).click());
      expect(container.querySelectorAll('.thinking-history-group .thinking-pill .thinking-collapse.expanded')).toHaveLength(1);
      expect(latestPillExpanded(container)).toBe(false);

      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(4)} isLive={false} isRunActive collapseForResponse={false} />);
      });
      expect(latestPill(container)?.textContent).toContain('Reasoning (Step 4)');
      expect(latestPillExpanded(container)).toBe(false);
    } finally {
      act(() => root.unmount());
    }
  });

  it('stays open across new live passes and pass completions once the user opened it', () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const renderWith = (segments: ThinkingSegment[]) => act(() => {
      root.render(<ThinkingSegments segments={segments} isLive isRunActive collapseForResponse={false} />);
    });

    try {
      renderWith(withLatestComplete(1, false));
      clickLatestPill(container);
      expect(latestPillExpanded(container)).toBe(true);

      renderWith(withLatestComplete(1, true));
      expect(latestPillExpanded(container)).toBe(true);

      renderWith(withLatestComplete(2, false));
      expect(latestPillExpanded(container)).toBe(true);

      renderWith(withLatestComplete(2, true));
      expect(latestPillExpanded(container)).toBe(true);
    } finally {
      act(() => root.unmount());
    }
  });

  it('keeps reasoning the user opened through the response and the end of the run', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(2)} isLive={false} isRunActive collapseForResponse={false} />);
      });
      clickLatestPill(container);

      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(2)} isLive={false} isRunActive collapseForResponse />);
      });
      expect(latestPillExpanded(container)).toBe(true);

      act(() => {
        root.render(<ThinkingSegments segments={makeSegments(2)} isLive={false} isRunActive={false} collapseForResponse />);
      });
      expect(container.querySelectorAll('.thinking-segments > .thinking-pill')).toHaveLength(1);
      expect(latestPillExpanded(container)).toBe(true);
    } finally {
      act(() => root.unmount());
    }
  });

  it('never opens reasoning on its own, even while a pass is live', () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const renderWith = (segments: ThinkingSegment[], collapseForResponse = false) => act(() => {
      root.render(<ThinkingSegments segments={segments} isLive isRunActive collapseForResponse={collapseForResponse} />);
    });

    try {
      renderWith(withLatestComplete(1, false));
      expect(latestPillExpanded(container)).toBe(false);

      renderWith(withLatestComplete(2, false));
      expect(latestPillExpanded(container)).toBe(false);

      renderWith(withLatestComplete(2, true), true);
      expect(latestPillExpanded(container)).toBe(false);
    } finally {
      act(() => root.unmount());
    }
  });

  it('stays closed after the user closes it, even when a new live pass starts', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<ThinkingSegments segments={withLatestComplete(1, false)} isLive isRunActive collapseForResponse={false} />);
      });
      expect(latestPillExpanded(container)).toBe(false);

      clickLatestPill(container);
      expect(latestPillExpanded(container)).toBe(true);

      clickLatestPill(container);
      expect(latestPillExpanded(container)).toBe(false);

      act(() => {
        root.render(<ThinkingSegments segments={withLatestComplete(2, false)} isLive isRunActive collapseForResponse={false} />);
      });
      expect(latestPillExpanded(container)).toBe(false);
    } finally {
      act(() => root.unmount());
    }
  });
});
