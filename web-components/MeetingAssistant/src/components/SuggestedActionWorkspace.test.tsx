import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingActionProposalDTO } from '../bridge/types';
import SuggestedActionWorkspace from './SuggestedActionWorkspace';

const promoteProposalToTodo = vi.fn();
const startProposalNow = vi.fn();
const openProposalTodo = vi.fn();
const openProposalAgentTask = vi.fn();
const promoteAllProposalsToTodos = vi.fn();
const dismissProposal = vi.fn();
const restoreProposal = vi.fn();
const updateProposal = vi.fn();

vi.mock('../bridge/meetingBridge', () => ({
  promoteProposalToTodo: (...args: unknown[]) => promoteProposalToTodo(...args),
  startProposalNow: (...args: unknown[]) => startProposalNow(...args),
  openProposalTodo: (...args: unknown[]) => openProposalTodo(...args),
  openProposalAgentTask: (...args: unknown[]) => openProposalAgentTask(...args),
  promoteAllProposalsToTodos: (...args: unknown[]) => promoteAllProposalsToTodos(...args),
  dismissProposal: (...args: unknown[]) => dismissProposal(...args),
  restoreProposal: (...args: unknown[]) => restoreProposal(...args),
  updateProposal: (...args: unknown[]) => updateProposal(...args),
}));

function makeProposal(overrides: Partial<MeetingActionProposalDTO> = {}): MeetingActionProposalDTO {
  return {
    id: 'proposal-1',
    sourceActionItemIndex: 0,
    sourceTask: 'Follow up with Alex about the launch checklist.',
    sourceContext: '[02:03] Alex: Could we schedule onboarding next week?\n[02:05] Sam: Tuesday afternoon works for the customer.',
    sourceTimestamp: 123,
    sourceSpeaker: 'Alex',
    suggestedAgentTask: 'Draft a follow-up email to Alex about the launch checklist.',
    capabilityType: 'email_draft',
    confidence: 0.9,
    whyBasilCanHelp: 'Basil can draft the follow-up from meeting context.',
    missingInformation: [],
    requiresUserConfirmation: false,
    workspaceSource: 'meeting-1',
    executionStatus: 'proposed',
    submittedAgentTaskId: null,
    todoId: null,
    todoStatus: null,
    lastError: null,
    isEditingDraft: false,
    draftPrompt: 'Draft a follow-up email to Alex about the launch checklist.',
    liveAgentStatus: null,
    ...overrides,
  };
}

describe('SuggestedActionWorkspace', () => {
  beforeEach(() => {
    promoteProposalToTodo.mockReset();
    startProposalNow.mockReset();
    openProposalTodo.mockReset();
    openProposalAgentTask.mockReset();
    promoteAllProposalsToTodos.mockReset();
    dismissProposal.mockReset();
    restoreProposal.mockReset();
    updateProposal.mockReset();
  });

  it('shows a bulk count that excludes dismissed and already-promoted proposals', () => {
    render(
      <SuggestedActionWorkspace
        proposals={[
          makeProposal({ id: 'p1', sourceTask: 'Keep this one' }),
          makeProposal({ id: 'p2', sourceTask: 'Keep this too', draftPrompt: 'Second draft' }),
          makeProposal({ id: 'p3', sourceTask: 'Dismissed item', executionStatus: 'dismissed' }),
          makeProposal({ id: 'p4', sourceTask: 'Already added', executionStatus: 'added_to_todos', todoId: 'todo-4' }),
        ]}
      />,
    );

    expect(screen.getByRole('button', { name: 'Add all 2 to To-Dos' })).toBeInTheDocument();
  });

  it('sends exactly one bulk intent and no per-card promotions when Add all is clicked', async () => {
    const user = userEvent.setup();
    render(
      <SuggestedActionWorkspace
        proposals={[
          makeProposal({ id: 'p1', sourceTask: 'First actionable' }),
          makeProposal({ id: 'p2', sourceTask: 'Second actionable', draftPrompt: 'Second draft' }),
        ]}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Add all 2 to To-Dos' }));

    expect(promoteAllProposalsToTodos).toHaveBeenCalledTimes(1);
    expect(promoteProposalToTodo).not.toHaveBeenCalled();
  });

  it('sends distinct start-now and add-to-todos intents from the card actions', async () => {
    const user = userEvent.setup();
    render(<SuggestedActionWorkspace proposals={[makeProposal({ executionMode: 'agent_assisted' })]} />);

    await user.click(screen.getByRole('button', { name: 'Start now' }));
    await user.click(screen.getByRole('button', { name: 'Add to To-Dos' }));

    expect(startProposalNow).toHaveBeenCalledWith('proposal-1');
    expect(promoteProposalToTodo).toHaveBeenCalledWith('proposal-1');
    expect(screen.queryByRole('button', { name: /Start without To-Do/i })).not.toBeInTheDocument();
  });

  it('keeps a To-Do-only candidate promotable and startable after review', async () => {
    const user = userEvent.setup();
    render(<SuggestedActionWorkspace proposals={[makeProposal({ executionMode: 'todo_only', capabilityType: 'todo' })]} />);

    await user.click(screen.getByRole('button', { name: 'Start now' }));

    expect(startProposalNow).toHaveBeenCalledWith('proposal-1');
    expect(screen.getByRole('button', { name: 'Start now' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Add to To-Dos' })).toBeEnabled();
    const proposedTask = screen.getByRole('region', { name: 'Proposed task' });
    expect(within(proposedTask).getByText('Proposed task')).toBeInTheDocument();
  });

  it('treats an omitted todo id from the Swift bridge as not promoted', () => {
    const proposal = makeProposal();
    delete (proposal as Partial<MeetingActionProposalDTO>).todoId;

    render(<SuggestedActionWorkspace proposals={[proposal]} />);

    expect(screen.getByRole('button', { name: 'Add all 1 to To-Dos' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Add to To-Dos' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'In To-Dos' })).not.toBeInTheDocument();
  });

  it('shows independent To-Do and Agent Task outcomes and opens their canonical destinations', async () => {
    const user = userEvent.setup();
    render(
      <SuggestedActionWorkspace
        proposals={[makeProposal({
          executionStatus: 'submitted',
          todoId: 'todo-1',
          todoStatus: 'ready_for_review',
          submittedAgentTaskId: 'agent-1',
          liveAgentStatus: 'completed',
        })]}
      />,
    );

    expect(screen.getByText('To-Do: Ready for review')).toBeInTheDocument();
    expect(screen.getByText('Paprika task: Completed')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open To-Do' }));
    await user.click(screen.getByRole('button', { name: 'Open in Paprika' }));
    expect(openProposalTodo).toHaveBeenCalledWith('todo-1');
    expect(openProposalAgentTask).toHaveBeenCalledWith('agent-1');
  });

  it('renders markdown steps in a non-editing proposed task', () => {
    render(
      <SuggestedActionWorkspace
        proposals={[makeProposal({
          sourceTask: '**Provider** review',
          draftPrompt: '1. Research **provider** options.\n2. Summarize trade-offs.\n3. Review with Avraham.',
        })]}
      />,
    );

    const proposedTask = document.querySelector('.meeting-proposal-draft-preview');
    const steps = Array.from(proposedTask?.querySelectorAll('ol > li') ?? []).map((item) => item.textContent);
    expect(steps).toEqual(['Research provider options.', 'Summarize trade-offs.', 'Review with Avraham.']);
    expect(proposedTask?.querySelector('strong')?.textContent).toBe('provider');
    expect(document.querySelector('.meeting-proposal-source-task')?.textContent).toBe('Provider review');
  });

  it('uses a cohesive card hierarchy with capability and agent-task subsections', () => {
    render(<SuggestedActionWorkspace proposals={[makeProposal()]} />);
    expect(screen.getByText('email draft', { selector: '.meeting-proposal-capability' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Follow up with Alex about the launch checklist.' }).querySelector('.meeting-proposal-capability-icon')).not.toBeNull();
    const contextSummary = screen.getByText('Transcript context').closest('summary');
    expect(contextSummary).not.toBeNull();
    expect(within(contextSummary as HTMLElement).getByText('02:03')).toBeInTheDocument();
    expect(screen.getByText(/Could we schedule onboarding next week/).closest('blockquote')).not.toBeNull();
    expect(screen.getByText('90% confidence').parentElement).not.toHaveTextContent('02:03');
    const agentTask = screen.getByRole('region', { name: 'Proposed task' });
    expect(within(agentTask).getByText('Proposed task')).toBeInTheDocument();
    expect(within(agentTask).getByText('Draft a follow-up email to Alex about the launch checklist.')).toBeInTheDocument();
  });

  it('collapses starting and submitting cards with compact progress text', () => {
    render(
      <SuggestedActionWorkspace
        proposals={[
          makeProposal({ id: 'starting-1', sourceTask: 'Starting card', executionStatus: 'starting' }),
          makeProposal({ id: 'adding-1', sourceTask: 'Adding card', executionStatus: 'submitting' }),
        ]}
      />,
    );

    expect(screen.getByText('Starting')).toBeInTheDocument();
    expect(screen.getByText('Adding')).toBeInTheDocument();
    expect(screen.queryByText('Basil can draft the follow-up from meeting context.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Starting card/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: /Adding card/ })).toHaveAttribute('aria-expanded', 'false');
  });

  it('reopens a failed start with a retained To-Do, shows Retry start, and disables add', async () => {
    const user = userEvent.setup();
    render(
      <SuggestedActionWorkspace
        proposals={[
          makeProposal({
            sourceTask: 'Failed start card',
            executionStatus: 'failed',
            todoId: 'todo-kept',
            lastError: 'Worker launch failed',
          }),
        ]}
      />,
    );

    expect(screen.getByRole('button', { name: /Failed start card/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('Worker launch failed');
    expect(screen.getByRole('button', { name: 'Retry start' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'In To-Dos' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Retry start' }));
    expect(startProposalNow).toHaveBeenCalledWith('proposal-1');
    expect(promoteProposalToTodo).not.toHaveBeenCalled();
  });

  it('hides the bulk button when no proposals are eligible', () => {
    render(
      <SuggestedActionWorkspace
        proposals={[
          makeProposal({ id: 'd1', executionStatus: 'dismissed', sourceTask: 'Dismissed only' }),
          makeProposal({ id: 'a1', executionStatus: 'added_to_todos', todoId: 'todo-a', sourceTask: 'Already added' }),
        ]}
      />,
    );

    expect(screen.queryByRole('button', { name: /Add all/ })).not.toBeInTheDocument();
  });

  it('keeps dismissed proposals separate from added To-Dos and allows restore', async () => {
    const user = userEvent.setup();
    render(
      <SuggestedActionWorkspace
        proposals={[
          makeProposal({ id: 'completed-1', executionStatus: 'completed', sourceTask: 'Completed follow-up' }),
          makeProposal({ executionStatus: 'dismissed', sourceTask: 'Dismissed follow-up' }),
        ]}
      />,
    );

    const addedToTodos = screen.getByText('Added to To-Dos (1)').closest('details');
    expect(addedToTodos).not.toBeNull();
    const dismissed = screen.getByText('Dismissed (1)').closest('details');
    expect(dismissed).not.toBeNull();
    expect(within(addedToTodos as HTMLElement).queryByText('Dismissed follow-up')).not.toBeInTheDocument();
    expect((addedToTodos as HTMLElement).querySelector('summary')).toHaveClass('meeting-proposal-group-summary');
    expect((dismissed as HTMLElement).querySelector('summary')).toHaveClass('meeting-proposal-group-summary');
    expect((addedToTodos as HTMLElement).querySelector('.meeting-proposal-group-chevron')).not.toBeNull();
    expect((dismissed as HTMLElement).querySelector('.meeting-proposal-group-chevron')).not.toBeNull();
    if (dismissed && !dismissed.open) {
      await user.click(within(dismissed).getByText('Dismissed (1)'));
    }
    await user.click(screen.getByRole('button', { name: /Dismissed follow-up/ }));
    const restore = await screen.findByRole('button', { name: 'Restore' });
    await user.click(restore);
    expect(restoreProposal).toHaveBeenCalledWith('proposal-1');
  });
});
