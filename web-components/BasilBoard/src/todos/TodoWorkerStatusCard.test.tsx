import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TodoWorkAttempt } from '../contracts';
import TodoWorkerStatusCard from './TodoWorkerStatusCard';

const bridgeMocks = vi.hoisted(() => ({
  openExistingAgentTaskWidget: vi.fn(),
  openExternalUrl: vi.fn(),
}));

vi.mock('../services/bridge', () => bridgeMocks);

function attempt(overrides: Partial<TodoWorkAttempt> = {}): TodoWorkAttempt {
  return {
    agent_task_id: 'worker-1',
    title: 'Research encryption options',
    status: 'processing',
    created_at: '2026-08-21T12:00:00Z',
    updated_at: '2026-08-21T12:01:00Z',
    attention: false,
    ...overrides,
  };
}

describe('TodoWorkerStatusCard', () => {
  beforeEach(() => {
    bridgeMocks.openExistingAgentTaskWidget.mockReset();
    bridgeMocks.openExternalUrl.mockReset();
  });

  it('renders live active progress and opens the exact Agent Task only on request', async () => {
    render(<TodoWorkerStatusCard attempt={attempt()} liveState={{ latestActivity: 'Reviewing key-rotation guidance' }} />);

    expect(screen.getByText('Paprika task in progress')).toBeInTheDocument();
    expect(screen.getByText('Reviewing key-rotation guidance')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open in Paprika' }));
    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledWith('worker-1');
  });

  it('renders the Agent Task title as plain text without markdown syntax', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ title: '**Encryption** options for `key_store`' })} />);

    expect(screen.getByText('Encryption options for key_store')).toHaveClass('todo-worker-status-card-title');
  });

  it('renders a terminal success outcome', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'completed', result_summary: 'Completed research.' })} />);

    expect(screen.getByText('Paprika task completed')).toBeInTheDocument();
    expect(screen.getByText('Completed research.')).toBeInTheDocument();
  });

  it('renders a partial outcome distinctly from a real failure, with the actual message inline', () => {
    render(
      <TodoWorkerStatusCard
        attempt={attempt({
          status: 'failed',
          result_severity: 'warning',
          outcome: 'partial',
          result_summary: 'Drafted 3 of 5 requested emails; two recipients had no address on file.',
        })}
      />,
    );

    expect(screen.getByText('Partial result')).toBeInTheDocument();
    expect(screen.queryByText('Paprika task failed')).not.toBeInTheDocument();
    expect(
      screen.getByText('Drafted 3 of 5 requested emails; two recipients had no address on file.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('partial')).not.toBeInTheDocument();
  });

  it('still labels a true failure as failed, distinct from partial', () => {
    render(
      <TodoWorkerStatusCard
        attempt={attempt({ status: 'failed', result_severity: 'error', result_summary: 'Provider timed out.' })}
      />,
    );

    expect(screen.getByText('Paprika task failed')).toBeInTheDocument();
    expect(screen.queryByText('Partial result')).not.toBeInTheDocument();
  });

  it('renders terminal result messages as safe Markdown', async () => {
    render(
      <TodoWorkerStatusCard
        attempt={attempt({
          status: 'completed',
          result_summary: '**Completed** the review.\n\n- Sent follow-up\n- Archived notes\n\n[Read summary](https://example.test/summary)',
        })}
      />,
    );

    expect(screen.getByText('Completed').tagName).toBe('STRONG');
    expect(screen.getByRole('list')).toHaveTextContent('Sent follow-up');
    await userEvent.click(screen.getByRole('link', { name: 'Read summary' }));
    expect(bridgeMocks.openExternalUrl).toHaveBeenCalledWith('https://example.test/summary');
  });

  it('strips unsafe Markdown HTML while retaining its text content', () => {
    render(
      <TodoWorkerStatusCard
        attempt={attempt({ status: 'completed', result_summary: '<a href="javascript:alert(1)">Safe text</a><img src="x" onerror="alert(1)">' })}
      />,
    );

    expect(screen.getByText('Safe text')).not.toHaveAttribute('href');
    expect(document.querySelector('.todo-worker-status-card-outcome img')).toBeNull();
  });

  it('renders a warning result with headings, a list, a link and long text through the shared markdown renderer', async () => {
    const longLine = 'verylongunbrokenwordwithoutspaces'.repeat(12);
    render(
      <TodoWorkerStatusCard
        attempt={attempt({
          status: 'completed',
          result_severity: 'warning',
          result_summary: `## What was confirmed\n\n- Item one\n- Item two\n\n[Details](https://example.test/d)\n\n${longLine}`,
        })}
      />,
    );

    const card = screen.getByRole('status');
    expect(card).toHaveClass('todo-worker-status-card--warning');
    const outcome = card.querySelector('.todo-worker-status-card-outcome')!;
    expect(outcome.querySelector('.home-markdown.home-markdown-task')).not.toBeNull();
    expect(screen.getByRole('heading', { name: 'What was confirmed' }).tagName).toBe('H2');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(outcome.textContent).toContain(longLine);
    await userEvent.click(screen.getByRole('link', { name: 'Details' }));
    expect(bridgeMocks.openExternalUrl).toHaveBeenCalledWith('https://example.test/d');
    expect(outcome.querySelector('[style]')).toBeNull();
  });

  it('shows no result section for an empty result message', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'completed', result_summary: '' })} />);

    expect(document.querySelector('.todo-worker-status-card-outcome-row')).toBeNull();
  });

  it('collapses long result previews until the user expands them', async () => {
    render(
      <TodoWorkerStatusCard
        attempt={attempt({ status: 'completed', result_summary: 'A'.repeat(601) })}
      />,
    );

    const preview = document.querySelector<HTMLDivElement>('.todo-worker-status-card-outcome');
    if (!preview) throw new Error('Expected the terminal result preview to render.');
    expect(preview).toHaveClass('is-truncated');
    const toggle = screen.getByRole('button', { name: 'Show full result' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(toggle);

    expect(preview).not.toHaveClass('is-truncated');
    expect(screen.getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('uses American-English copy for canceled Agent Tasks', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'canceled' })} />);

    expect(screen.getByText('Paprika task canceled')).toBeInTheDocument();
  });

  it('presents needs-attention worker tasks as an alert', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'awaiting_user_input', attention: true })} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Paprika task needs your input');
    expect(screen.getByRole('button', { name: 'Respond in Paprika' })).toBeInTheDocument();
  });

  it('keeps long and empty activity states usable', () => {
    const longActivity = 'A'.repeat(1024);
    const { rerender } = render(
      <TodoWorkerStatusCard attempt={attempt()} liveState={{ latestActivity: longActivity }} />,
    );
    expect(screen.getByText(longActivity)).toBeInTheDocument();

    rerender(<TodoWorkerStatusCard attempt={attempt()} liveState={{}} />);
    expect(screen.queryByText(longActivity)).not.toBeInTheDocument();
    expect(screen.getByText('Paprika task in progress')).toBeInTheDocument();
  });

  it.each(['capturing', 'routing', 'processing', 'awaiting_provider_delegation', 'awaiting_delegated_agents'])(
    'mirrors the Agent Task sidebar processing spinner while %s',
    (status) => {
      const { container } = render(<TodoWorkerStatusCard attempt={attempt({ status })} />);

      expect(container.querySelector('.todo-worker-status-card-indicator .agent-task-processing-spinner')).not.toBeNull();
      expect(container.querySelector('.todo-worker-status-card-icon')).toBeNull();
    },
  );

  it('mirrors the sidebar paused glyph instead of the dots when paused', () => {
    const { container } = render(<TodoWorkerStatusCard attempt={attempt({ status: 'paused' })} />);

    expect(container.querySelector('.todo-worker-status-card-indicator svg[aria-label="Paused"]')).not.toBeNull();
    expect(container.querySelector('.agent-task-processing-spinner')).toBeNull();
  });

  it('mirrors the sidebar awaiting-input glyph for needs-attention tasks', () => {
    const { container } = render(<TodoWorkerStatusCard attempt={attempt({ status: 'awaiting_user_input', attention: true })} />);

    expect(container.querySelector('.todo-worker-status-card-indicator svg')).not.toBeNull();
    expect(container.querySelector('.agent-task-processing-spinner')).toBeNull();
  });

  it('keeps the result icon for terminal tasks and a static neutral icon for unrecognized statuses', () => {
    const terminal = render(<TodoWorkerStatusCard attempt={attempt({ status: 'completed', result_summary: 'Done.' })} />);
    expect(terminal.container.querySelector('.todo-worker-status-card-icon')).toHaveTextContent('✓');
    expect(terminal.container.querySelector('.todo-worker-status-card-indicator')).toBeNull();
    terminal.unmount();

    const unknown = render(<TodoWorkerStatusCard attempt={attempt({ status: 'mystery_state' })} />);
    expect(unknown.container.querySelector('.todo-worker-status-card-icon')).toHaveTextContent('⋯');
    expect(unknown.container.querySelector('.agent-task-processing-spinner')).toBeNull();
  });
  it('shows a waiting state with the next check time instead of a partial result when a follow-up is scheduled', () => {
    const { container } = render(
      <TodoWorkerStatusCard
        attempt={attempt({
          status: 'completed',
          result_severity: 'warning',
          result_summary: 'The delegated agent is still running.',
          next_follow_up_at: '2026-10-12T12:30:00+00:00',
        })}
      />,
    );

    expect(screen.getByRole('status', { name: 'Waiting to check again' })).toBeInTheDocument();
    expect(screen.queryByText('Partial result')).not.toBeInTheDocument();
    expect(screen.getByText(/Paprika will check again automatically at .+\./)).toBeInTheDocument();
    expect(container.querySelector('.todo-worker-status-card--waiting')).not.toBeNull();
    const icon = container.querySelector('.todo-worker-status-card-icon');
    expect(icon).not.toHaveTextContent('↻');
    expect(icon?.querySelector('span[style*="mask-image"]')).not.toBeNull();
    expect(screen.getByText('The delegated agent is still running.')).toBeInTheDocument();
  });

  it('still announces the waiting state when the next check time cannot be parsed', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'completed', next_follow_up_at: 'not-a-date' })} />);

    expect(screen.getByText('Paprika will check again automatically.')).toBeInTheDocument();
  });

  it('ignores a scheduled follow-up on a canceled task and shows the normal terminal label without one', () => {
    const canceled = render(
      <TodoWorkerStatusCard attempt={attempt({ status: 'canceled', next_follow_up_at: '2026-10-12T12:30:00+00:00' })} />,
    );
    expect(screen.getByRole('status', { name: 'Paprika task canceled' })).toBeInTheDocument();
    canceled.unmount();

    render(<TodoWorkerStatusCard attempt={attempt({ status: 'completed', result_severity: 'warning', next_follow_up_at: null })} />);
    expect(screen.getByRole('status', { name: 'Partial result' })).toBeInTheDocument();
  });

  it('does not show the waiting state while the task is still running', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'processing', next_follow_up_at: '2026-10-12T12:30:00+00:00' })} />);

    expect(screen.getByText('Paprika task in progress')).toBeInTheDocument();
    expect(screen.queryByText('Waiting to check again')).not.toBeInTheDocument();
  });
});
