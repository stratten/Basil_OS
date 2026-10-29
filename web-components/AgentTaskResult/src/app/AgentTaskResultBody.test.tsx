// @vitest-environment jsdom

import { createRef, type ComponentProps } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import { AgentTaskResultBody } from './AgentTaskResultBody';

vi.mock('../components/Header', () => ({
  default: ({ expandedTaskTitle }: { expandedTaskTitle?: string }) => (
    <header className="widget-header" data-expanded-task-title={expandedTaskTitle ?? ''}>Header</header>
  ),
}));
vi.mock('../components/Sidebar', () => ({
  default: () => <aside className="sidebar">Sidebar</aside>,
}));
vi.mock('../components/ScheduledAgentTaskDetail', () => ({
  default: () => <section>Scheduled task</section>,
}));
vi.mock('../components/DetachedTaskPlaceholder', () => ({
  default: () => <section>Detached task</section>,
}));
vi.mock('./AgentTaskDetailSurface', () => ({
  AgentTaskDetailSurface: () => <main className="agent-task-detail-surface">Result</main>,
}));

const displaySource = {
  agentTaskId: 'task-1',
  rootTaskId: 'task-1',
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
    detailTrayOpen: true,
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

describe('AgentTaskResultBody', () => {
  it('keeps the result subtree mounted but inert while the window is collapsed', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskResultBody {...bodyProps({ isChromeCollapsed: true, detailTrayOpen: true })} />,
    );

    const headerStart = markup.indexOf('class="agent-task-header-shell"');
    const bodyStart = markup.indexOf('class="widget-body"');
    expect(headerStart).toBeGreaterThan(-1);
    expect(bodyStart).toBeGreaterThan(headerStart);
    expect(markup).toContain('class="widget-body" hidden="" aria-hidden="true" inert=""');
    expect(markup).toContain('class="agent-task-detail-surface"');
    expect(markup).not.toContain('calc(100% -');
  });

  it('keeps the task title in a detached window header while expanded', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskResultBody
        {...bodyProps({
          isChromeCollapsed: false,
          detachedRootTaskId: 'task-1',
          displaySource: { ...displaySource, taskTitle: 'Review the Lido token' },
        })}
      />,
    );

    expect(markup).toContain('data-expanded-task-title="Review the Lido token"');
  });

  it('leaves the main window header without an expanded task title', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskResultBody
        {...bodyProps({
          isChromeCollapsed: false,
          detachedRootTaskId: null,
          displaySource: { ...displaySource, taskTitle: 'Review the Lido token' },
        })}
      />,
    );

    expect(markup).toContain('data-expanded-task-title=""');
  });
});
