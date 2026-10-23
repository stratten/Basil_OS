import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../bridge/meetingBridge', () => ({
  copyText: vi.fn(),
  openCompanionAssistantSession: vi.fn(),
  openProposalAgentTask: vi.fn(),
  openProposalTodo: vi.fn(),
}));

import { openCompanionAssistantSession, openProposalAgentTask, openProposalTodo } from '../bridge/meetingBridge';
import CompanionProposalCard from './CompanionProposalCard';
import type { CompanionItem, CompanionProposalInfo, CompanionProposalResult } from './types';

function info(overrides: Partial<CompanionProposalInfo> = {}): CompanionProposalInfo {
  return {
    proposal_id: 'pr-1',
    action: 'todo',
    title: 'Add a renewal reminder',
    instruction: 'Remind me to renew the contract.',
    authority: 'review',
    state: 'proposed',
    todo_id: null,
    agent_task_id: null,
    error: null,
    auto_started: false,
    ...overrides,
  };
}

function card(overrides: Partial<CompanionProposalInfo> = {}): CompanionItem {
  return {
    id: 'p1',
    seq: 0,
    kind: 'proposal',
    text: 'Add a renewal reminder',
    confidence: 0.9,
    citations: [],
    no_source: false,
    transcript_range: { start: 61, end: 63, turn_ids: [] },
    trigger: 'investigation',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    proposal: info(overrides),
  };
}

function result(overrides: Partial<CompanionProposalResult> = {}): CompanionProposalResult {
  return { state: 'started', title: 'Add a renewal reminder', instruction: 'Remind me to renew the contract.', todo_id: 't-1', agent_task_id: null, error: null, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CompanionProposalCard', () => {
  it('shows the title, the instruction and the kind of action, and starts nothing by itself', () => {
    const onDecide = vi.fn();
    render(<CompanionProposalCard item={card()} contextText="" onDecide={onDecide} />);
    expect(screen.getByLabelText('Proposed To-Do at [01:01]')).toBeInTheDocument();
    expect(screen.getByText('Add a renewal reminder', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Remind me to renew the contract.')).toBeInTheDocument();
    expect(onDecide).not.toHaveBeenCalled();
  });

  it('approves, disables both buttons while the request runs, and re-enables them afterwards', async () => {
    let finish: (value: CompanionProposalResult | null) => void = () => undefined;
    const onDecide = vi.fn(() => new Promise<CompanionProposalResult | null>((resolve) => { finish = resolve; }));
    render(<CompanionProposalCard item={card()} contextText="" onDecide={onDecide} />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(onDecide).toHaveBeenCalledWith('p1', 'approve');
    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeDisabled();
    finish(result());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Dismiss' })).toBeEnabled());
  });

  it('dismisses through the same decision callback', () => {
    const onDecide = vi.fn(async () => result({ state: 'dismissed', todo_id: null }));
    render(<CompanionProposalCard item={card()} contextText="" onDecide={onDecide} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onDecide).toHaveBeenCalledWith('p1', 'dismiss');
  });

  it('opens the To-Do that a started proposal created', () => {
    render(<CompanionProposalCard item={card({ state: 'started', todo_id: 't-9' })} contextText="" onDecide={vi.fn()} />);
    expect(screen.getByText('Added to your To-Do list.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Open To-Do' }));
    expect(openProposalTodo).toHaveBeenCalledWith('t-9');
  });

  it('opens the Agent Task and says when a watch started it by itself', () => {
    render(<CompanionProposalCard item={card({ action: 'agent_task', state: 'started', agent_task_id: 'a-3', auto_started: true })} contextText="" onDecide={vi.fn()} />);
    expect(screen.getByText('Sent to an Agent Task. It started by itself because of a watch you created.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open Agent Task' }));
    expect(openProposalAgentTask).toHaveBeenCalledWith('a-3');
  });

  it('offers Try Again with the error after a failed start and approves again', () => {
    const onDecide = vi.fn(async () => result());
    render(<CompanionProposalCard item={card({ state: 'failed', error: 'The To-Do worker is not ready yet.' })} contextText="" onDecide={onDecide} />);
    expect(screen.getByRole('alert')).toHaveTextContent('The To-Do worker is not ready yet.');
    fireEvent.click(screen.getByRole('button', { name: 'Try Again' }));
    expect(onDecide).toHaveBeenCalledWith('p1', 'approve');
  });

  it('hands an approved Assistant Session proposal to the native window with its context', async () => {
    const onDecide = vi.fn(async () => result({ state: 'handed_off', todo_id: null, instruction: 'Talk through the renewal options.' }));
    render(<CompanionProposalCard item={card({ action: 'assistant_session' })} contextText="The renewal date is 3 March." onDecide={onDecide} />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(openCompanionAssistantSession).toHaveBeenCalledWith('Talk through the renewal options.', 'The renewal date is 3 March.'));
  });

  it('does not open an Assistant Session when the request failed or the start failed', async () => {
    const failing = vi.fn(async () => null);
    const { unmount } = render(<CompanionProposalCard item={card({ action: 'assistant_session' })} contextText="ctx" onDecide={failing} />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled());
    unmount();
    const failed = vi.fn(async () => result({ state: 'failed', error: 'Nope.' }));
    render(<CompanionProposalCard item={card({ action: 'assistant_session' })} contextText="ctx" onDecide={failed} />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(failed).toHaveBeenCalled());
    expect(openCompanionAssistantSession).not.toHaveBeenCalled();
  });

  it('says a watch asked for it and shows a dismissed card without buttons', () => {
    const { rerender } = render(<CompanionProposalCard item={card({ authority: 'watch' })} contextText="" onDecide={vi.fn()} />);
    expect(screen.getByText('From a watch you set')).toBeInTheDocument();
    rerender(<CompanionProposalCard item={card({ state: 'dismissed' })} contextText="" onDecide={vi.fn()} />);
    expect(screen.getByText('Dismissed.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders nothing for an item without a proposal block', () => {
    const plain = { ...card(), proposal: undefined };
    const { container } = render(<CompanionProposalCard item={plain} contextText="" onDecide={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
