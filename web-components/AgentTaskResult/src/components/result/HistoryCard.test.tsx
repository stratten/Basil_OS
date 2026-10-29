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

describe('HistoryCard result footer', () => {
  function footerOf(item: AgentTaskHistoryItem): Document {
    return new DOMParser().parseFromString(
      renderToStaticMarkup(<HistoryCard item={item} isExpanded onToggle={() => {}} />),
      'text/html',
    );
  }

  it('puts the time then the recorded model below the result, not beside the heading', () => {
    const doc = footerOf(historyItem({ modelUsed: 'gpt-5-mini' }));
    const footer = doc.querySelector('.result-footer');

    expect(footer).not.toBeNull();
    expect(doc.querySelector('.history-card__result-heading')?.textContent).toBe('Result:');
    expect(Array.from(footer?.children ?? []).map(child => child.className)).toEqual(['result-footer__time', 'result-footer__model']);
    expect(footer?.querySelector('time')?.getAttribute('datetime')).toBe('2026-09-24T12:00:00.000Z');
    expect(footer?.querySelector('.result-footer__model')?.textContent).toBe('· gpt-5-mini');
    expect(doc.querySelector('.history-card__result')?.compareDocumentPosition(footer as Node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('shows only the time when no model was recorded', () => {
    const doc = footerOf(historyItem());
    expect(doc.querySelector('.result-footer__time')).not.toBeNull();
    expect(doc.querySelector('.result-footer__model')).toBeNull();
  });

  it('prefers the latest timeline entry over the turn timestamp', () => {
    const doc = footerOf(historyItem({
      executionTimeline: [
        { id: 'a', type: 'step', timestamp: '2026-09-24T12:07:00Z', content: 'Wrote it' },
        { id: 'b', type: 'step', timestamp: '2026-09-24T12:03:00Z', content: 'Read it' },
      ],
    }));
    expect(doc.querySelector('time')?.getAttribute('datetime')).toBe('2026-09-24T12:07:00.000Z');
  });

  it('is absent from the collapsed card', () => {
    const collapsed = renderToStaticMarkup(
      <HistoryCard item={historyItem({ modelUsed: 'gpt-5-mini' })} isExpanded={false} onToggle={() => {}} />,
    );
    expect(collapsed).not.toContain('result-footer');
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

describe('HistoryCard connections', () => {
  it('lists the connections the run was told to use beside its references', () => {
    const markup = renderToStaticMarkup(
      <HistoryCard
        item={historyItem({ connection_references: [{ id: 'conn-gmail', name: 'Gmail' }] })}
        isExpanded
        onToggle={() => {}}
      />,
    );

    expect(markup).toContain('data-attachment-kind="connection"');
    expect(markup).toContain('>Gmail<');
  });

  it('shows no connection chips for a run that used none, or for an older record without the field', () => {
    for (const item of [historyItem(), historyItem({ connection_references: [] })]) {
      const markup = renderToStaticMarkup(<HistoryCard item={item} isExpanded onToggle={() => {}} />);
      expect(markup).not.toContain('data-attachment-kind="connection"');
    }
  });
});
