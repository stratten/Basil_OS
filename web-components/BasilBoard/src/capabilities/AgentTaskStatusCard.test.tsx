import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationMessageItem } from '../contracts';
import AgentTaskStatusCard from './AgentTaskStatusCard';

const bridgeMocks = vi.hoisted(() => ({ openExistingAgentTaskWidget: vi.fn() }));
vi.mock('../services/bridge', () => bridgeMocks);

function message(
  lifecycle: string,
  extra: Partial<Record<string, unknown>> = {},
): ConversationMessageItem {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: '',
    timestamp: '2026-07-30T12:00:00Z',
    metadata: {
      conversation_turn: {
        route: 'agent_task',
        lifecycle,
        agent_task_id: 'task-1',
        terminal_outcome: null,
        status_text: null,
        ...extra,
      },
    },
  };
}

function activitySummary(overrides: Record<string, unknown> = {}) {
  return {
    agent_task_id: 'task-1',
    lifecycle: 'processing',
    latest_activity: 'Writing the requested report.',
    workflow: { completed_steps: 1, total_steps: 3 },
    artifacts: [],
    artifact_count: 0,
    verification_status: 'pending',
    requires_user_attention: false,
    ...overrides,
  };
}

function activityArtifact(index: number, displayName = `artifact-${index}.md`) {
  return {
    artifact_id: `artifact-${index}`,
    display_name: displayName,
    artifact_kind: 'file',
    lifecycle: 'ready',
    verification: { status: 'unknown' },
  };
}

function baseProps() {
  return {
    onPreviewArtifact: vi.fn(),
    onViewAllArtifacts: vi.fn(),
  };
}

describe('AgentTaskStatusCard', () => {
  beforeEach(() => {
    bridgeMocks.openExistingAgentTaskWidget.mockReset();
  });

  it('renders nothing for a non-agent_task message', () => {
    const { container } = render(
      <AgentTaskStatusCard
        {...baseProps()}
        message={{
          id: 'x', role: 'assistant', content: '', timestamp: 't', metadata: {},
        }}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it('renders a running card with a spinner and no outcome', () => {
    render(<AgentTaskStatusCard {...baseProps()} message={message('running', { status_text: 'Agent task is working.' })} />);

    expect(screen.getByRole('status', { name: 'Paprika task in progress' })).toBeTruthy();
    expect(screen.getByText('Agent task is working.')).toBeTruthy();
    expect(document.querySelector('.chats-agent-task-icon.is-spinning')).toBeTruthy();
  });

  it('renders a terminal card without the spinner and with the outcome', () => {
    render(<AgentTaskStatusCard {...baseProps()} message={message('completed', { terminal_outcome: 'Agent task completed.' })} />);

    expect(screen.getByText('Agent task completed.')).toBeTruthy();
    expect(document.querySelector('.chats-agent-task-icon.is-spinning')).toBeNull();
  });

  it('suppresses a duplicate terminal outcome that exactly matches the detail line', () => {
    render(<AgentTaskStatusCard
      {...baseProps()}
      message={message('completed', {
        status_text: null,
        terminal_outcome: 'Writing the requested report.',
        activity_summary: activitySummary(),
      })}
    />);

    expect(screen.getAllByText('Writing the requested report.')).toHaveLength(1);
  });

  it('shows a terminal outcome that is semantically distinct from the detail line', () => {
    render(<AgentTaskStatusCard
      {...baseProps()}
      message={message('completed', {
        status_text: null,
        terminal_outcome: 'Agent task completed.',
        activity_summary: activitySummary(),
      })}
    />);

    expect(screen.getByText('Writing the requested report.')).toBeTruthy();
    expect(screen.getByText('Agent task completed.')).toBeTruthy();
  });

  it('renders up to two file chips and a View all control for a running task', async () => {
    const user = userEvent.setup();
    const props = baseProps();
    const artifacts = [activityArtifact(1), activityArtifact(2), activityArtifact(3)];
    render(<AgentTaskStatusCard {...props} message={message('running', {
      activity_summary: activitySummary({ artifacts, artifact_count: 3 }),
    })}
    />);

    expect(screen.getByText('artifact-1.md')).toBeTruthy();
    expect(screen.getByText('artifact-2.md')).toBeTruthy();
    expect(screen.queryByText('artifact-3.md')).toBeNull();
    const viewAll = screen.getByRole('button', { name: 'View all (3)' });
    expect(viewAll).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'artifact-1.md' }));
    expect(props.onPreviewArtifact).toHaveBeenCalledWith('task-1', 'artifact-1');

    await user.click(viewAll);
    expect(props.onViewAllArtifacts).toHaveBeenCalledWith('task-1');
  });

  it('retains file chips for a terminal task', () => {
    const props = baseProps();
    render(<AgentTaskStatusCard {...props} message={message('completed', {
      terminal_outcome: 'Agent task completed.',
      activity_summary: activitySummary({ artifacts: [activityArtifact(1)], artifact_count: 1 }),
    })}
    />);

    expect(screen.getByRole('button', { name: 'artifact-1.md' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'View all (1)' })).toBeTruthy();
  });

  it('renders no Files row for zero artifacts', () => {
    render(<AgentTaskStatusCard {...baseProps()} message={message('running', { activity_summary: activitySummary() })} />);

    expect(screen.queryByLabelText('Paprika task files')).toBeNull();
  });

  it('suppresses a malformed raw activity summary while retaining the status card', () => {
    render(<AgentTaskStatusCard {...baseProps()} message={message('running', {
      activity_summary: activitySummary({ raw_path: '/private/report.md' }),
    })}
    />);

    expect(screen.getByRole('status', { name: 'Paprika task in progress' })).toBeTruthy();
    expect(screen.queryByText('Writing the requested report.')).toBeNull();
  });

  it('opens the canonical Agent Task surface through the bridge', async () => {
    const user = userEvent.setup();
    render(<AgentTaskStatusCard {...baseProps()} message={message('failed', { terminal_outcome: 'Agent task failed.' })} />);

    await user.click(screen.getByRole('button', { name: 'Open in Paprika' }));

    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledWith('task-1');
  });

  it('announces attention and opens the matching task once when a live summary arrives', () => {
    const { rerender } = render(
      <AgentTaskStatusCard
        {...baseProps()}
        message={message('running', {
          status_text: 'Agent task needs your input.',
          requires_user_attention: true,
          attention_id: 'checkpoint-1',
        })}
      />,
    );

    expect(screen.getByRole('alert', { name: 'Paprika task needs your input' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Respond in Paprika' })).toBeTruthy();
    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledTimes(1);
    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenLastCalledWith('task-1');

    rerender(
      <AgentTaskStatusCard
        {...baseProps()}
        message={message('running', {
          status_text: 'Agent task needs your input.',
          requires_user_attention: true,
          attention_id: 'checkpoint-1',
          activity_summary: activitySummary(),
        })}
      />,
    );

    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledTimes(1);
  });

  it('opens the same task again for a later distinct attention ID', () => {
    const { rerender } = render(
      <AgentTaskStatusCard
        {...baseProps()}
        message={message('running', {
          requires_user_attention: true,
          attention_id: 'checkpoint-1',
        })}
      />,
    );

    rerender(
      <AgentTaskStatusCard
        {...baseProps()}
        message={message('running', {
          requires_user_attention: true,
          attention_id: 'checkpoint-2',
        })}
      />,
    );

    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenCalledTimes(2);
    expect(bridgeMocks.openExistingAgentTaskWidget).toHaveBeenLastCalledWith('task-1');
  });

  it('is memoized so it does not re-render on unrelated parent updates', () => {
    expect((AgentTaskStatusCard as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'));
  });
});
