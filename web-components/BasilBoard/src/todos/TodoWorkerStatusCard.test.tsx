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

    expect(screen.getByText('Agent task in progress')).toBeInTheDocument();
    expect(screen.getByText('Reviewing key-rotation guidance')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open Agent Task' }));
    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledWith('worker-1');
  });

  it('renders a terminal success outcome', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'completed', result_summary: 'Completed research.' })} />);

    expect(screen.getByText('Agent task completed')).toBeInTheDocument();
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
    expect(screen.queryByText('Agent task failed')).not.toBeInTheDocument();
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

    expect(screen.getByText('Agent task failed')).toBeInTheDocument();
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

  it('uses American-English copy for cancelled Agent Tasks', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'cancelled' })} />);

    expect(screen.getByText('Agent task canceled')).toBeInTheDocument();
  });

  it('presents needs-attention worker tasks as an alert', () => {
    render(<TodoWorkerStatusCard attempt={attempt({ status: 'awaiting_user_input', attention: true })} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Agent task needs your input');
    expect(screen.getByRole('button', { name: 'Respond in Agent Task' })).toBeInTheDocument();
  });

  it('keeps long and empty activity states usable', () => {
    const longActivity = 'A'.repeat(1024);
    const { rerender } = render(
      <TodoWorkerStatusCard attempt={attempt()} liveState={{ latestActivity: longActivity }} />,
    );
    expect(screen.getByText(longActivity)).toBeInTheDocument();

    rerender(<TodoWorkerStatusCard attempt={attempt()} liveState={{}} />);
    expect(screen.queryByText(longActivity)).not.toBeInTheDocument();
    expect(screen.getByText('Agent task in progress')).toBeInTheDocument();
  });
});
