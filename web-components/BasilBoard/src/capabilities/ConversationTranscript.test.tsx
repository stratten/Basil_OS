import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ConversationMessageItem } from '../contracts';
import ConversationTranscript from './ConversationTranscript';

vi.mock('../services/bridge', () => ({ openExistingAgentTaskWidget: vi.fn() }));

function baseProps(messages: ConversationMessageItem[]) {
  return {
    viewportRef: { current: null },
    messages,
    loading: false,
    loadError: undefined,
    selectedId: 'conversation-1',
    onRetryLoad: vi.fn(),
    onPinnedChange: vi.fn(),
    onCopy: vi.fn(),
    onPreviewArtifact: vi.fn(),
    onViewAllArtifacts: vi.fn(),
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

function activityArtifact(index: number) {
  return {
    artifact_id: `artifact-${index}`,
    display_name: `artifact-${index}.md`,
    artifact_kind: 'file',
    lifecycle: 'ready',
    verification: { status: 'unknown' },
  };
}

describe('ConversationTranscript agent task rendering', () => {
  it('renders the status card instead of a bubble before narration starts', () => {
    render(<ConversationTranscript {...baseProps([{
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      timestamp: '2026-07-30T12:00:00Z',
      metadata: {
        conversation_turn: {
          route: 'agent_task',
          lifecycle: 'running',
          agent_task_id: 'task-1',
          terminal_outcome: null,
          status_text: 'Agent task is working.',
        },
      },
    }])}
    />);

    expect(screen.getByRole('status', { name: 'Agent task in progress' })).toBeTruthy();
    expect(document.querySelector('.chats-message-bubble')).toBeNull();
  });

  it('forwards file-chip and view-all selections to the passed handlers', async () => {
    const user = userEvent.setup();
    const artifacts = [activityArtifact(1), activityArtifact(2), activityArtifact(3)];
    const props = baseProps([{
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      timestamp: '2026-07-30T12:00:00Z',
      metadata: {
        conversation_turn: {
          route: 'agent_task',
          lifecycle: 'running',
          agent_task_id: 'task-1',
          terminal_outcome: null,
          status_text: 'Agent task is working.',
          activity_summary: activitySummary({ artifacts, artifact_count: 3 }),
        },
      },
    }]);
    render(<ConversationTranscript {...props} />);

    expect(screen.getByText('Writing the requested report.')).toBeTruthy();
    expect(document.querySelector('.chats-message-bubble')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'artifact-1.md' }));
    expect(props.onPreviewArtifact).toHaveBeenCalledWith('task-1', 'artifact-1');

    await user.click(screen.getByRole('button', { name: 'View all (3)' }));
    expect(props.onViewAllArtifacts).toHaveBeenCalledWith('task-1');
  });

  it('retains the completed Agent Task provenance card above narration content', () => {
    render(<ConversationTranscript {...baseProps([{
      id: 'assistant-1',
      role: 'assistant',
      content: 'Here is the answer.',
      timestamp: '2026-07-30T12:00:00Z',
      metadata: {
        conversation_turn: {
          route: 'agent_task',
          lifecycle: 'completed',
          agent_task_id: 'task-1',
          terminal_outcome: 'Agent task completed.',
          status_text: null,
        },
      },
    }])}
    />);

    expect(screen.getByText('Here is the answer.')).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Agent task completed' })).toBeTruthy();
  });

  it('never shows the status card or activity disclosure for a user message', () => {
    render(<ConversationTranscript {...baseProps([{
      id: 'user-1',
      role: 'user',
      content: 'Hello',
      timestamp: '2026-07-30T12:00:00Z',
      metadata: {
        conversation_turn: {
          route: 'agent_task',
          lifecycle: 'running',
          agent_task_id: 'task-1',
          activity_summary: activitySummary(),
        },
      },
    }])}
    />);

    expect(document.querySelector('.chats-agent-task-card')).toBeNull();
    expect(screen.queryByRole('button', { name: 'artifact-1.md' })).toBeNull();
  });

  it('offers rich text and Markdown copy actions with visible confirmation', async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn().mockResolvedValue(undefined);
    const props = baseProps([{
      id: 'assistant-1',
      role: 'assistant',
      content: 'Copy me',
      timestamp: '2026-07-30T12:00:00Z',
      metadata: {},
    }]);
    props.onCopy = onCopy;
    render(<ConversationTranscript {...props} />);

    await user.click(screen.getByRole('button', { name: 'Copy rich text' }));
    expect(onCopy).toHaveBeenCalledWith('Copy me', 'richText');
    expect(screen.getByRole('button', { name: 'Copy rich text copied' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Copy Markdown' }));
    expect(onCopy).toHaveBeenCalledWith('Copy me', 'markdown');
    expect(screen.getByRole('button', { name: 'Copy Markdown copied' })).toBeTruthy();
  });
});
