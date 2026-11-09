// @vitest-environment jsdom

import { act, createRef, type ComponentProps } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import { agentStore } from '../store/agentStore';
import { AgentTaskResultBody } from './AgentTaskResultBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../components/Header', () => ({
  default: ({ isProcessing }: { isProcessing: boolean }) => (
    <header data-testid="header" data-processing={String(isProcessing)}>Header</header>
  ),
}));
vi.mock('../components/Sidebar', () => ({ default: () => <aside>Sidebar</aside> }));
vi.mock('../components/ScheduledAgentTaskDetail', () => ({ default: () => <section>Scheduled task</section> }));
vi.mock('../components/DetachedTaskPlaceholder', () => ({ default: () => <section>Detached task</section> }));
vi.mock('./AgentTaskDetailSurface', () => ({ AgentTaskDetailSurface: () => <main>Result</main> }));

const displaySource = {
  agentTaskId: 'focused',
  rootTaskId: 'focused',
  originalPrompt: 'Create report',
  status: 'completed',
  result: 'Created report.',
  delegatedProviderReportCards: [],
  structuredFiles: [],
  referencePaths: [],
  agentTaskHistory: [],
  progressSteps: [],
  executionTimeline: [],
  stepDetails: [],
  showWorkflowPlan: false,
  isStreaming: false,
  checkpointAvailable: false,
  thinkingSegments: [],
} satisfies DisplayableAgentTask;

function bodyProps(overrides: Partial<ComponentProps<typeof AgentTaskResultBody>> = {}): ComponentProps<typeof AgentTaskResultBody> {
  return {
    rootRef: createRef<HTMLDivElement>(),
    embedded: false,
    isChromeCollapsed: true,
    detachedRootTaskId: null,
    displaySourceDetached: false,
    detachedDisplayRootId: null,
    detachedRootsElsewhere: new Set(),
    detailTrayOpen: false,
    detailTrayWidth: 400,
    onDetailTrayWidthChange: () => {},
    onDetailTrayModeChange: () => {},
    displaySource,
    selectedAgent: null,
    selectedDetail: undefined,
    selectedDetailId: null,
    selectedDetailOwnerId: null,
    followLatestDetail: false,
    hasNewerDetail: false,
    sidebarExpanded: false,
    initialized: true,
    initiallyProcessing: false,
    selectedScheduledAgentTaskId: null,
    createScheduledMode: false,
    scheduledListVersion: 0,
    viewedDetail: displaySource,
    pendingAgentTaskSelection: null,
    missedRunToasts: [],
    captureState: null,
    textFollowUpMode: false,
    isProcessing: false,
    isCapturing: false,
    bubbleMode: 'ambient',
    isCollapseIconRotated: false,
    showCancelStop: false,
    onCancelRunningAgent: () => {},
    runPauseState: undefined,
    isPausing: false,
    onPauseRunningAgent: () => {},
    onResumeRunningAgent: () => {},
    onToggleChromeCollapsed: () => {},
    onToggleSidebar: () => {},
    onViewHistoricalAgentTask: () => {},
    onViewScheduledAgentTask: () => {},
    onCreateScheduledAgentTask: () => {},
    onAgentTaskDeleted: () => {},
    onScheduledCreated: () => {},
    onScheduledUpdated: () => {},
    onExitCreateMode: () => {},
    onViewAgentTask: () => {},
    onRetry: () => {},
    onContinue: () => {},
    onSelectDetail: () => {},
    onCancelTextFollowUp: () => {},
    onStartVoiceFollowUp: () => {},
    onOpenDetailTray: () => {},
    onCloseDetailTray: () => {},
    onJumpToLatestDetail: () => {},
    ...overrides,
  };
}

describe('AgentTaskResultBody collapsed header attention', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  function render(overrides: Partial<ComponentProps<typeof AgentTaskResultBody>> = {}) {
    act(() => root.render(<AgentTaskResultBody {...bodyProps(overrides)} />));
  }

  function bubbleIsProcessing(): boolean {
    return container.querySelector('[data-testid="header"]')?.getAttribute('data-processing') === 'true';
  }

  function addOtherTask(status: 'processing' | 'completed' | 'awaitingInput') {
    act(() => {
      agentStore.registerAgent('other', 'request', { select: false });
      agentStore.updateStatus('other', status);
    });
  }

  beforeEach(() => {
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
  });

  it('shows the processing bubble when another task is working while the widget is collapsed', () => {
    addOtherTask('processing');
    render();
    expect(bubbleIsProcessing()).toBe(true);
  });

  it('shows the processing bubble when another task is waiting on the user', () => {
    addOtherTask('awaitingInput');
    render();
    expect(bubbleIsProcessing()).toBe(true);
  });

  it('follows the other task as it starts and finishes', () => {
    render();
    expect(bubbleIsProcessing()).toBe(false);

    addOtherTask('processing');
    expect(bubbleIsProcessing()).toBe(true);

    act(() => agentStore.updateStatus('other', 'completed'));
    expect(bubbleIsProcessing()).toBe(false);
  });

  it('leaves the bubble to the focused task while the widget is expanded', () => {
    addOtherTask('processing');
    render({ isChromeCollapsed: false });
    expect(bubbleIsProcessing()).toBe(false);
  });

  it('ignores a task another window owns and a detached-task window', () => {
    addOtherTask('processing');
    render({ detachedRootsElsewhere: new Set(['other']) });
    expect(bubbleIsProcessing()).toBe(false);

    render({ detachedRootTaskId: 'focused' });
    expect(bubbleIsProcessing()).toBe(false);
  });
});
