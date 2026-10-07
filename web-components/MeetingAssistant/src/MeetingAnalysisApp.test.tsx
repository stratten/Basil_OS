import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingActionProposalDTO, MeetingAnalysisResultDTO, MeetingBridgeEvent } from './bridge/types';
import { settleHostWindowResize } from '@shared/settleHostWindowResize';
import MeetingAnalysisApp from './MeetingAnalysisApp';

const mocks = vi.hoisted(() => ({
  eventHandler: null as ((event: MeetingBridgeEvent) => void) | null,
  copyText: vi.fn(),
  exportAnalysis: vi.fn(),
  retryAnalysisModes: vi.fn(),
  viewAnalysis: vi.fn(),
  reportReady: vi.fn(),
  toggleWindowCollapse: vi.fn(),
  reportChromeHeight: vi.fn(),
}));

vi.mock('./bridge/meetingBridge', () => ({
  registerEventHandler: (cb: (event: MeetingBridgeEvent) => void) => {
    mocks.eventHandler = cb;
  },
  reportReady: () => mocks.reportReady(),
  toggleWindowCollapse: (collapsed: boolean) => mocks.toggleWindowCollapse(collapsed),
  reportChromeHeight: (...args: unknown[]) => mocks.reportChromeHeight(...args),
  copyText: (...args: unknown[]) => mocks.copyText(...args),
  exportAnalysis: (...args: unknown[]) => mocks.exportAnalysis(...args),
  retryAnalysisModes: (...args: unknown[]) => mocks.retryAnalysisModes(...args),
  viewAnalysis: (...args: unknown[]) => mocks.viewAnalysis(...args),
  closeWindow: vi.fn(),
  minimizeWindow: vi.fn(),
  promoteProposalToTodo: vi.fn(),
  startProposalNow: vi.fn(),
  promoteAllProposalsToTodos: vi.fn(),
  dismissProposal: vi.fn(),
  restoreProposal: vi.fn(),
  updateProposal: vi.fn(),
}));

function makeProposal(overrides: Partial<MeetingActionProposalDTO> = {}): MeetingActionProposalDTO {
  return {
    id: 'proposal-1',
    sourceActionItemIndex: 0,
    sourceTask: 'Follow up with Alex',
    sourceContext: null,
    sourceTimestamp: null,
    sourceSpeaker: null,
    suggestedAgentTask: 'Draft a follow-up email to Alex',
    capabilityType: 'email_draft',
    confidence: 0.9,
    whyBasilCanHelp: 'Basil can draft the follow-up',
    missingInformation: [],
    requiresUserConfirmation: false,
    workspaceSource: 'meeting-1',
    executionStatus: 'proposed',
    submittedAgentTaskId: null,
    todoId: null,
    todoStatus: null,
    lastError: null,
    isEditingDraft: false,
    draftPrompt: 'Draft a follow-up email to Alex',
    liveAgentStatus: null,
    ...overrides,
  };
}

function makeResult(overrides: Partial<MeetingAnalysisResultDTO> = {}): MeetingAnalysisResultDTO {
  return {
    meetingId: 'meeting-1',
    filename: 'analysis.json',
    analyzedAt: '2026-08-14 10:00',
    modelUsed: 'local-model',
    requestedModes: ['summary', 'action_items', 'suggested_actions'],
    modesAnalyzed: ['summary', 'action_items', 'suggested_actions'],
    failedModes: null,
    safetyOmissions: null,
    customInstructions: null,
    actionItems: [{ id: 'ai-1', task: 'Send the brief', assignedTo: 'Alex', deadline: 'Friday', priority: null, context: '', timestamp: 0, speaker: null }],
    suggestedActions: [makeProposal()],
    summary: 'The team agreed to ship Friday.',
    decisions: null,
    questionsAnswers: null,
    sentimentAnalysis: null,
    customAnalysis: null,
    transcriptDuration: 125,
    speakerCount: 2,
    processingTime: 4.2,
    meetingName: 'Launch Review',
    meetingPurpose: null,
    participants: null,
    formattedDuration: '2m 5s',
    formattedProcessingTime: '4.2s',
    ...overrides,
  };
}

function publishResult(result: MeetingAnalysisResultDTO, proposals = result.suggestedActions ?? []) {
  act(() => {
    mocks.eventHandler?.({
      type: 'snapshot',
      revision: 1,
      selectionGeneration: 1,
      protocolVersion: 4,
      analysisResult: result,
      proposals,
    });
  });
}

describe('MeetingAnalysisApp', () => {
  beforeEach(() => {
    mocks.eventHandler = null;
    mocks.copyText.mockReset();
    mocks.exportAnalysis.mockReset();
    mocks.retryAnalysisModes.mockReset();
    mocks.viewAnalysis.mockReset();
    mocks.reportReady.mockReset();
    mocks.toggleWindowCollapse.mockReset();
    mocks.reportChromeHeight.mockReset();
  });

  it('puts Copy All and Export in the title bar and uses one tab per analysis mode', () => {
    const heightSpy = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('meeting-window-chrome') ? 56 : 0;
    });

    try {
      render(<MeetingAnalysisApp />);
      publishResult(makeResult());

      const chrome = screen.getByText('Meeting Analysis').closest('.meeting-window-chrome');
      expect(chrome).not.toBeNull();
      expect(within(chrome as HTMLElement).getByRole('button', { name: 'Copy All' })).toBeInTheDocument();
      expect(within(chrome as HTMLElement).getByRole('button', { name: 'Export' })).toBeInTheDocument();
      expect(mocks.reportChromeHeight).toHaveBeenLastCalledWith(56);

      expect(screen.queryByRole('tab', { name: 'Results' })).not.toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Action Items' })).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('tab', { name: 'To-Do Candidates' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Summary' })).toBeInTheDocument();
      expect(screen.getByText('Send the brief')).toBeInTheDocument();
      expect(screen.getByText('1', { selector: '.meeting-action-item-number' })).toBeInTheDocument();
      expect(screen.getByText('Alex', { selector: '.meeting-action-item-meta' }).querySelector('svg')).not.toBeNull();
      expect(screen.getByText('Friday', { selector: '.meeting-action-item-meta' }).querySelector('svg')).not.toBeNull();
      expect(screen.queryByText('The team agreed to ship Friday.')).not.toBeInTheDocument();
    } finally {
      heightSpy.mockRestore();
    }
  });

  it('places the bulk To-Do action in the suggested-actions header grid', async () => {
    const user = userEvent.setup();
    render(<MeetingAnalysisApp />);
    publishResult(makeResult());

    await user.click(screen.getByRole('tab', { name: 'To-Do Candidates' }));

    const results = screen.getByRole('heading', { name: 'To-Do Candidates' }).closest('.meeting-analysis-results');
    expect(results).toHaveClass('meeting-analysis-results--suggested-actions');
    expect(within(results as HTMLElement).getByRole('button', { name: 'Add all 1 to To-Dos' })).toBeInTheDocument();
  });

  it('shows a mode-specific omission notice without exposing transcript text', () => {
    render(<MeetingAnalysisApp />);
    publishResult(makeResult({
      safetyOmissions: [{
        id: 'action-items-20-20-omitted',
        mode: 'action_items',
        startTimestamp: 20,
        endTimestamp: 20,
        segmentCount: 1,
        provider: 'anthropic',
        refusalCategory: 'general_harms',
        refusalExplanation: 'The provider declined this range.',
        recovery: 'omitted_refused_line',
      }],
    }));

    expect(screen.getByRole('status')).toHaveTextContent('Some transcript content was omitted');
    expect(screen.getByRole('status')).toHaveTextContent('00:20');
    expect(screen.queryByText('The provider declined this range.')).not.toBeInTheDocument();
  });

  it('discloses provider restriction details only when a refusal explanation exists', async () => {
    const user = userEvent.setup();
    render(<MeetingAnalysisApp />);
    publishResult(makeResult({
      failedModes: [{
        id: 'summary',
        mode: 'summary',
        category: 'safety',
        message: 'anthropic_output_format ended incompletely: finish_reason=refusal',
        retryable: false,
        refusalCategory: 'general_harms',
        refusalExplanation: 'The provider declined this request.',
      }],
    }));

    await user.click(screen.getByText('Provider restriction details'));
    expect(screen.getByText('The provider declined this request.')).toBeInTheDocument();
  });

  it('copies only the selected tab from the section copy button', async () => {
    const user = userEvent.setup();
    render(<MeetingAnalysisApp />);
    publishResult(makeResult());

    await user.click(screen.getByRole('tab', { name: 'Summary' }));
    await user.click(screen.getByRole('button', { name: 'Copy this section' }));

    expect(mocks.copyText).toHaveBeenCalledTimes(1);
    const [text] = mocks.copyText.mock.calls[0];
    expect(text).toContain('## Summary');
    expect(text).toContain('The team agreed to ship Friday.');
    expect(text).not.toContain('Send the brief');
    expect(text).not.toContain('Follow up with Alex');
  });

  it('copies every completed mode from the title-bar Copy All button', async () => {
    const user = userEvent.setup();
    render(<MeetingAnalysisApp />);
    publishResult(makeResult());

    await user.click(screen.getByRole('button', { name: 'Copy All' }));

    expect(mocks.copyText).toHaveBeenCalledTimes(1);
    const [text] = mocks.copyText.mock.calls[0];
    expect(text).toContain('# Launch Review');
    expect(text).toContain('## Action Items');
    expect(text).toContain('## To-Do Candidates');
    expect(text).toContain('## Summary');
  });

  it('hides title-bar copy and export while the window is collapsed', async () => {
    const user = userEvent.setup();
    render(<MeetingAnalysisApp />);
    publishResult(makeResult());
    const actionItemsTab = screen.getByRole('tab', { name: 'Action Items' });

    await user.click(screen.getByRole('button', { name: 'Collapse' }));

    expect(screen.queryByRole('button', { name: 'Copy All' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Export' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Action Items' })).not.toBeInTheDocument();
    expect(actionItemsTab.isConnected).toBe(true);
    expect(actionItemsTab.closest('[hidden]')).toHaveAttribute('inert');

    await user.click(screen.getByRole('button', { name: 'Expand' }));
    await settleHostWindowResize();
    expect(screen.getByRole('tab', { name: 'Action Items' })).toBe(actionItemsTab);
  });

  it('does not carry handled To-Do state into a newly completed analysis', async () => {
    const user = userEvent.setup();
    render(<MeetingAnalysisApp />);
    publishResult(
      makeResult({ filename: 'old-analysis.json' }),
      [makeProposal({ executionStatus: 'added_to_todos', todoId: 'todo-old' })],
    );
    await user.click(screen.getByRole('tab', { name: 'To-Do Candidates' }));
    expect(screen.getByText('Added to To-Dos (1)')).toBeInTheDocument();

    act(() => {
      mocks.eventHandler?.({
        type: 'analysisResultDelta',
        revision: 2,
        selectionGeneration: 1,
        protocolVersion: 4,
        analysisResult: makeResult({ filename: 'new-analysis.json', suggestedActions: [makeProposal()] }),
      });
    });

    await user.click(screen.getByRole('tab', { name: 'To-Do Candidates' }));
    expect(screen.getByRole('button', { name: 'Add to To-Dos' })).toBeEnabled();
    expect(screen.queryByText('Added to To-Dos (1)')).not.toBeInTheDocument();
  });
});
