// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import type { ThinkingSegment } from '../../types';
import { ReasoningWithInteractions } from './InteractionExchange';
import type { UserInteraction } from './userInteractions';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const waiting: UserInteraction = {
  id: 'cp',
  entryId: 'user_interaction_cp',
  kind: 'clarification',
  status: 'waiting',
  prompt: 'Which hotel did you mean?',
  askedAt: '2026-10-04T23:40:02+00:00',
  responseHidden: false,
  options: [],
};

const answered: UserInteraction = {
  ...waiting,
  status: 'answered',
  response: 'La Fantaisie',
  respondedAt: '2026-10-04T23:44:00+00:00',
};

const beforeQuestion: ThinkingSegment = {
  iteration: 1,
  text: 'Looking up the hotel',
  isComplete: true,
  recordedAt: '2026-10-04T23:39:00+00:00',
};

const afterAnswer: ThinkingSegment = {
  iteration: 2,
  text: 'Searching shops nearby',
  isComplete: false,
  recordedAt: '2026-10-04T23:45:00+00:00',
};

describe('ReasoningWithInteractions follow state', () => {
  it('carries reasoning the user opened past an exchange into the next reasoning block', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <ReasoningWithInteractions segments={[beforeQuestion]} interactions={[waiting]} isLive isRunActive collapseForResponse={false} />,
        );
      });
      const header = container.querySelector('.thinking-segments .execution-steps-header') as HTMLElement;
      act(() => header.click());
      expect(container.querySelector('.thinking-segments .thinking-collapse.expanded')).not.toBeNull();

      act(() => {
        root.render(
          <ReasoningWithInteractions
            segments={[beforeQuestion, afterAnswer]}
            interactions={[answered]}
            isLive
            isRunActive
            collapseForResponse={false}
          />,
        );
      });

      const tail = container.querySelector('.reasoning-with-interactions > .thinking-segments:last-child');
      expect(tail?.textContent).toContain('Reasoning');
      expect(tail?.querySelector('.thinking-collapse.expanded')).not.toBeNull();
      expect(tail?.textContent).toContain('Searching shops nearby');
    } finally {
      act(() => root.unmount());
    }
  });

  it('folds open reasoning away once the run is complete', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <ReasoningWithInteractions segments={[beforeQuestion]} interactions={[]} isLive isRunActive collapseForResponse={false} />,
        );
      });
      act(() => (container.querySelector('.thinking-segments .execution-steps-header') as HTMLElement).click());
      expect(container.querySelector('.thinking-collapse.expanded')).not.toBeNull();

      act(() => {
        root.render(
          <ReasoningWithInteractions
            segments={[{ ...beforeQuestion, isComplete: true }]}
            interactions={[]}
            isLive={false}
            isRunActive={false}
            collapseForResponse={false}
            runComplete
          />,
        );
      });
      expect(container.querySelector('.thinking-collapse.expanded')).toBeNull();

      act(() => (container.querySelector('.thinking-segments .execution-steps-header') as HTMLElement).click());
      expect(container.querySelector('.thinking-collapse.expanded')).not.toBeNull();
    } finally {
      act(() => root.unmount());
    }
  });
});
