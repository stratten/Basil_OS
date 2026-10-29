import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingActionProposalDTO } from '../bridge/types';
import SuggestedActionWorkspace from './SuggestedActionWorkspace';
import { DEPARTURE_TOTAL_MS } from './useDepartingProposals';

vi.mock('../bridge/meetingBridge', () => ({
  promoteProposalToTodo: vi.fn(),
  startProposalNow: vi.fn(),
  openProposalTodo: vi.fn(),
  openProposalAgentTask: vi.fn(),
  promoteAllProposalsToTodos: vi.fn(),
  dismissProposal: vi.fn(),
  restoreProposal: vi.fn(),
  updateProposal: vi.fn(),
}));

function makeProposal(id: string, overrides: Partial<MeetingActionProposalDTO> = {}): MeetingActionProposalDTO {
  return {
    id,
    sourceActionItemIndex: 0,
    sourceTask: `Task ${id}`,
    sourceContext: '',
    sourceTimestamp: null,
    sourceSpeaker: null,
    suggestedAgentTask: 'Do the thing.',
    capabilityType: 'todo',
    confidence: 0.9,
    whyBasilCanHelp: `Why ${id}.`,
    missingInformation: [],
    requiresUserConfirmation: false,
    workspaceSource: 'meeting-1',
    executionStatus: 'proposed',
    submittedAgentTaskId: null,
    todoId: null,
    todoStatus: null,
    lastError: null,
    isEditingDraft: false,
    draftPrompt: 'Do the thing.',
    liveAgentStatus: null,
    ...overrides,
  };
}

function reducedMotion(matches: boolean) {
  window.matchMedia = ((query: string) => ({ matches, media: query, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, onchange: null, dispatchEvent: () => false })) as typeof window.matchMedia;
}

describe('SuggestedActionWorkspace departures', () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    vi.useFakeTimers();
    reducedMotion(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    window.matchMedia = originalMatchMedia;
  });

  it('keeps a card that was just added to To-Dos in place with a confirmation, then moves it to the group', () => {
    const before = [makeProposal('a'), makeProposal('b')];
    const view = render(<SuggestedActionWorkspace proposals={before} />);
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'added_to_todos', todoId: 'todo-a' }), makeProposal('b')]} />);

    const cards = Array.from(document.querySelectorAll('.meeting-proposal-card'));
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveClass('is-departing');
    expect(cards[1]).not.toHaveClass('is-departing');
    expect(screen.getByRole('status')).toHaveTextContent('✓ Added to To-Dos');
    expect(screen.queryByText('Added to To-Dos (1)')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open To-Do' })).not.toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(DEPARTURE_TOTAL_MS); });

    expect(document.querySelectorAll('.is-departing')).toHaveLength(0);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText('Added to To-Dos (1)')).toBeInTheDocument();
    expect(document.querySelectorAll('.meeting-proposal-card')).toHaveLength(2);
  });

  it('fixes the measured height and fades the card once the confirmation has been held', () => {
    const view = render(<SuggestedActionWorkspace proposals={[makeProposal('a')]} />);
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'added_to_todos', todoId: 'todo-a' })]} />);
    const card = document.querySelector('.meeting-proposal-card') as HTMLElement;
    expect(card).not.toHaveClass('is-departing-leave');

    act(() => { vi.advanceTimersByTime(460); });

    expect(card).toHaveClass('is-departing-leave');
    expect(card.style.height).toBe('0px');
  });

  it('confirms a dismissal the same way', () => {
    const view = render(<SuggestedActionWorkspace proposals={[makeProposal('a')]} />);
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'dismissed' })]} />);
    expect(screen.getByRole('status')).toHaveTextContent('Dismissed');
    act(() => { vi.advanceTimersByTime(DEPARTURE_TOTAL_MS); });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText('Dismissed (1)')).toBeInTheDocument();
  });

  it('never plays a departure for cards that were already handled when the page opened', () => {
    render(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'added_to_todos', todoId: 'todo-a' })]} />);
    expect(document.querySelectorAll('.is-departing')).toHaveLength(0);
    expect(screen.getByText('Added to To-Dos (1)')).toBeInTheDocument();
  });

  it('moves a card straight to its group under reduced motion', () => {
    reducedMotion(true);
    const view = render(<SuggestedActionWorkspace proposals={[makeProposal('a')]} />);
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'added_to_todos', todoId: 'todo-a' })]} />);
    expect(document.querySelectorAll('.is-departing')).toHaveLength(0);
    expect(screen.getByText('Added to To-Dos (1)')).toBeInTheDocument();
  });

  it('brings a restored card back without leaving it half departed', () => {
    const view = render(<SuggestedActionWorkspace proposals={[makeProposal('a')]} />);
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'dismissed' })]} />);
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a')]} />);
    expect(document.querySelectorAll('.is-departing')).toHaveLength(0);
    act(() => { vi.advanceTimersByTime(DEPARTURE_TOTAL_MS); });
    expect(screen.getByRole('button', { name: /Task a/ })).toBeInTheDocument();
    expect(screen.queryByText('Dismissed (1)')).not.toBeInTheDocument();
  });

  it('closes a card body over a short animation instead of removing it at once', () => {
    const view = render(<SuggestedActionWorkspace proposals={[makeProposal('a')]} />);
    expect(screen.getByText('Why a.')).toBeInTheDocument();
    view.rerender(<SuggestedActionWorkspace proposals={[makeProposal('a', { executionStatus: 'submitting' })]} />);
    expect(screen.getByText('Why a.').closest('.meeting-proposal-body')).toHaveClass('is-closing');
    act(() => { vi.advanceTimersByTime(340); });
    expect(screen.queryByText('Why a.')).not.toBeInTheDocument();
  });
});
