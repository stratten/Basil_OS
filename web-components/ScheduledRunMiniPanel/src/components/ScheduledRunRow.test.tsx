import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import ScheduledRunRow from './ScheduledRunRow';

describe('ScheduledRunRow', () => {
  it('renders the scheduled task title as plain text without markdown syntax', () => {
    const markup = renderToStaticMarkup(
      <ScheduledRunRow
        row={{
          runId: 'run-1',
          scheduledAgentTaskId: 'scheduled-1',
          agentTaskId: 'agent-1',
          title: '**Weekly** `inbox_triage` summary',
          currentStep: 'Planning',
          status: 'running',
          startedAt: 0,
        }}
        onOpen={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(markup).toContain('<div class="mini-panel-row-title">Weekly inbox_triage summary</div>');
  });
});
