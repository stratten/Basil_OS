// @vitest-environment jsdom

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AgentTaskHistoryItem } from '../../types';
import { HistoryCard } from './HistoryCard';

function historyItem(overrides: Partial<AgentTaskHistoryItem> = {}): AgentTaskHistoryItem {
  return {
    id: 'historical-task',
    agentTaskText: 'Review the report',
    result: 'The report is complete.',
    files: [],
    reference_paths: [],
    timestamp: '2026-09-24T12:00:00.000Z',
    ...overrides,
  };
}

describe('HistoryCard reasoning trace', () => {
  it('renders the existing reasoning pill only for historical turns with a trace', () => {
    const withReasoning = renderToStaticMarkup(
      <HistoryCard
        item={historyItem({
          thinkingSegments: [{ iteration: 1, text: 'Review the evidence.', isComplete: true }],
        })}
        isExpanded
        onToggle={() => {}}
      />,
    );
    const withoutReasoning = renderToStaticMarkup(
      <HistoryCard item={historyItem()} isExpanded onToggle={() => {}} />,
    );

    expect(withReasoning).toContain('Reasoning');
    expect(withReasoning).toContain('thinking-segments');
    expect(withoutReasoning).not.toContain('thinking-segments');
  });
});
