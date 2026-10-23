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

  const baseRow = {
    runId: 'run-2',
    scheduledAgentTaskId: 'scheduled-2',
    agentTaskId: 'agent-2',
    title: 'Check changes',
    currentStep: 'Running a command',
    status: 'running' as const,
    startedAt: 0,
  };

  it('says the run needs approval instead of showing a stale step when the task is paused for the user', () => {
    const markup = renderToStaticMarkup(
      <ScheduledRunRow row={{ ...baseRow, awaitingInput: true }} onOpen={vi.fn()} onDismiss={vi.fn()} />,
    );

    expect(markup).toContain('mini-panel-row--needs-input');
    expect(markup).toContain('mini-panel-row-status needs-input');
    expect(markup).toContain('Needs your approval');
    expect(markup).not.toContain('Running a command');
  });

  it('keeps the step text for a working run and ignores the flag once the run has finished', () => {
    const working = renderToStaticMarkup(
      <ScheduledRunRow row={baseRow} onOpen={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(working).toContain('Running a command');
    expect(working).not.toContain('needs-input');

    const finished = renderToStaticMarkup(
      <ScheduledRunRow row={{ ...baseRow, status: 'finished', taskStatus: 'completed', outcome: 'success', awaitingInput: true }} onOpen={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(finished).toContain('Completed');
    expect(finished).not.toContain('needs-input');
  });
});

describe('ScheduledRunRow outcome language', () => {
  const finishedRow = {
    runId: 'run-3',
    scheduledAgentTaskId: 'scheduled-3',
    agentTaskId: 'agent-3',
    title: 'Check changes',
    currentStep: 'Running a command',
    status: 'finished' as const,
    startedAt: 0,
  };

  function render(patch: Record<string, unknown>) {
    return renderToStaticMarkup(
      <ScheduledRunRow row={{ ...finishedRow, ...patch }} onOpen={vi.fn()} onDismiss={vi.fn()} />,
    );
  }

  it('draws a partial result with the shared half-filled green mark and never as a failure', () => {
    const markup = render({ taskStatus: 'failed', outcome: 'partial', verificationStatus: 'resolved' });

    expect(markup).toContain('mini-panel-row-status partial outcome-partial-mark');
    expect(markup).toContain('Partial result');
    expect(markup).not.toContain('status failed');
    expect(markup).not.toContain('Running a command');
  });

  it('draws a real failure as the failure dot with the shared label', () => {
    const markup = render({ taskStatus: 'failed', outcome: 'failed', verificationStatus: 'resolved' });

    expect(markup).toContain('mini-panel-row-status failed');
    expect(markup).toContain('Couldn&#x27;t complete');
  });

  it('draws a clean success as the completed dot', () => {
    const markup = render({ taskStatus: 'completed', outcome: 'success', verificationStatus: 'resolved' });

    expect(markup).toContain('mini-panel-row-status completed');
    expect(markup).toContain('Completed');
  });

  it('shows a result that is still being verified as working, not as a verdict', () => {
    const markup = render({ status: 'running', taskStatus: 'failed', outcome: 'partial', verificationStatus: 'pending' });

    expect(markup).toContain('mini-panel-row-status running');
    expect(markup).toContain('Verifying the outcome');
    expect(markup).not.toContain('partial');
  });

  it('draws a paused or stopped task with its own neutral dot and label', () => {
    expect(render({ taskStatus: 'paused' })).toContain('mini-panel-row-status paused');
    expect(render({ taskStatus: 'paused' })).toContain('Paused');
    expect(render({ taskStatus: 'canceled' })).toContain('mini-panel-row-status canceled');
    expect(render({ taskStatus: 'canceled' })).toContain('Canceled');
  });
});
