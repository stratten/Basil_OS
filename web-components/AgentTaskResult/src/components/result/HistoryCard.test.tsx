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

describe('HistoryCard status and run details', () => {
  const finalizerResult = 'The report is complete.\n\n• Active app at request: Pages\n\n• Steps: 2/2 completed';

  it('no longer draws the always-green success check on a failed turn', () => {
    const collapsed = renderToStaticMarkup(
      <HistoryCard item={historyItem({ status: 'failed', errorMessage: 'The tool crashed.' })} isExpanded={false} onToggle={() => {}} />,
    );
    const expanded = renderToStaticMarkup(
      <HistoryCard item={historyItem({ status: 'failed', errorMessage: 'The tool crashed.' })} isExpanded onToggle={() => {}} />,
    );

    expect(collapsed).not.toContain('fill="var(--success-base)"');
    expect(expanded).not.toContain('fill="var(--success-base)"');
  });

  it('keeps finalizer metadata out of the collapsed preview and in a collapsed run details section when expanded', () => {
    const collapsed = renderToStaticMarkup(
      <HistoryCard item={historyItem({ result: finalizerResult })} isExpanded={false} onToggle={() => {}} />,
    );
    const expanded = renderToStaticMarkup(
      <HistoryCard item={historyItem({ result: finalizerResult })} isExpanded onToggle={() => {}} />,
    );

    expect(collapsed).toContain('The report is complete.');
    expect(collapsed).not.toContain('Active app at request');
    expect(expanded).toContain('run-details-toggle');
    expect(expanded).toContain('2 tool calls · Pages');
    expect(expanded).not.toContain('Active app at request');
  });

  it('flattens markdown in the collapsed request and result preview', () => {
    const collapsed = renderToStaticMarkup(
      <HistoryCard
        item={historyItem({
          agentTaskText: 'Add a **reminder** for `Wednesday`',
          result: 'Done — reminder created:\n- **Reminder:** "Buy cat t-shirt"\n- **Due:** Wednesday at 9:00 AM',
        })}
        isExpanded={false}
        onToggle={() => {}}
      />,
    );

    expect(collapsed).toContain('Add a reminder for Wednesday');
    expect(collapsed).toContain('Done — reminder created: Reminder: &quot;Buy cat t-shirt&quot; Due: Wednesday at 9:00 AM');
    expect(collapsed).not.toContain('**');
    expect(collapsed).not.toContain('`');
  });
});
