// @vitest-environment jsdom
import { act, memo } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentState } from '../types';
import { createAgentState } from '../store/agentStore/stateFactory';
import type { AgentTaskRowProps } from './sidebar/AgentTaskRow';
import Sidebar, { isLiveAgentTaskStatus } from './Sidebar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const { listAgentTasks, getAgentTaskDetail, deleteAgentTask } = vi.hoisted(() => ({
  listAgentTasks: vi.fn(),
  getAgentTaskDetail: vi.fn(),
  deleteAgentTask: vi.fn(),
}));

// Mutable holder so individual tests can control the agent list returned by
// useAllAgents() across re-renders without re-declaring the module mock.
const { allAgentsRef, getAgentMock, stableSelectAgent } = vi.hoisted(() => ({
  allAgentsRef: { current: [] as AgentState[] },
  getAgentMock: vi.fn((_id: string) => undefined as AgentState | undefined),
  // Must be a single stable reference -- unlike the real useSelectAgent()
  // (which wraps in useCallback), a plain `() => () => {}` mock would hand
  // back a brand-new closure on every render, poisoning every row's
  // onSelect prop identity and defeating the very memoization this file
  // tests for.
  stableSelectAgent: () => {},
}));

vi.mock('../services/api', () => ({
  deleteAgentTask,
  getAgentTaskDetail,
  isApiReady: () => true,
  listAgentTasks,
}));

vi.mock('../store/agentStore', () => ({
  useAllAgents: () => allAgentsRef.current,
  useSelectAgent: () => stableSelectAgent,
  agentStore: {
    getSelectedAgentId: () => undefined,
    getAgent: (id: string) => getAgentMock(id),
    removeAgent: vi.fn(),
  },
}));

vi.mock('../services/bridge', () => ({
  openDetachedAgentTask: vi.fn(),
  startNewAgentTaskCapture: vi.fn(),
}));

// Wraps the *real* AgentTaskRow (still rendering its actual markup, so the
// other tests in this file keep working unchanged) in an outer memo()
// component that records a render per row id. Because the wrapper is itself
// memoized with the same shallow-prop-equality semantics as the production
// component, it bails out under exactly the same conditions the real
// AgentTaskRow would -- making its render count a faithful proxy for
// whether Sidebar's memoization fix is actually preventing re-renders.
const { agentTaskRowRenderCounts } = vi.hoisted(() => ({
  agentTaskRowRenderCounts: new Map<string, number>(),
}));

vi.mock('./sidebar/AgentTaskRow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./sidebar/AgentTaskRow')>();
  const RealAgentTaskRow = actual.AgentTaskRow;
  function TrackedAgentTaskRow(props: AgentTaskRowProps) {
    agentTaskRowRenderCounts.set(props.id, (agentTaskRowRenderCounts.get(props.id) ?? 0) + 1);
    return <RealAgentTaskRow {...props} />;
  }
  return { ...actual, AgentTaskRow: memo(TrackedAgentTaskRow) };
});

function collapsedSidebarMarkup(): string {
  return renderToStaticMarkup(
    <Sidebar
      isExpanded={false}
      canLoadData={false}
      onToggle={() => {}}
      onViewHistoricalAgentTask={() => {}}
      onViewAgentTask={() => {}}
      onViewScheduledAgentTask={() => {}}
      onCreateScheduledAgentTask={() => {}}
    />,
  );
}

describe('Sidebar', () => {
  beforeEach(() => {
    allAgentsRef.current = [];
    getAgentMock.mockReset();
    getAgentMock.mockImplementation(() => undefined);
    agentTaskRowRenderCounts.clear();
    deleteAgentTask.mockReset();
    deleteAgentTask.mockResolvedValue({ success: true });
  });

  it('routes every nonterminal backend task status through live hydration', () => {
    expect(isLiveAgentTaskStatus('capturing')).toBe(true);
    expect(isLiveAgentTaskStatus('routing')).toBe(true);
    expect(isLiveAgentTaskStatus('processing')).toBe(true);
    expect(isLiveAgentTaskStatus('awaiting_user_input')).toBe(true);
    expect(isLiveAgentTaskStatus('needs_clarification')).toBe(true);
    expect(isLiveAgentTaskStatus('completed')).toBe(false);
    expect(isLiveAgentTaskStatus('failed')).toBe(false);
    expect(isLiveAgentTaskStatus('cancelled')).toBe(false);
  });

  it('opens a live history row through the task hydrator instead of historical detail', async () => {
    listAgentTasks.mockResolvedValue({
      agentTasks: [{
        id: 'pending-provider-task',
        original_prompt: 'Run the provider fixture',
        timestamp: '2026-08-12T19:00:00.000Z',
        status: 'processing',
        result_preview: '',
        file_count: 0,
        follow_up_count: 0,
      }],
      total_count: 1,
      has_more: false,
    });
    const onViewAgentTask = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      await act(async () => {
        root.render(
          <Sidebar
            isExpanded
            canLoadData
            onToggle={() => {}}
            onViewHistoricalAgentTask={() => {}}
            onViewAgentTask={onViewAgentTask}
            onViewScheduledAgentTask={() => {}}
            onCreateScheduledAgentTask={() => {}}
          />,
        );
      });

      await vi.waitFor(() => {
        expect(container.querySelector('.sidebar-row')).not.toBeNull();
      });
      act(() => {
        container.querySelector<HTMLElement>('.sidebar-row > div')?.click();
      });

      expect(onViewAgentTask).toHaveBeenCalledWith('pending-provider-task');
      expect(getAgentTaskDetail).not.toHaveBeenCalled();
    } finally {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('always renders the bundled sidebar symbol', () => {
    const markup = collapsedSidebarMarkup();
    expect(markup).toContain('sidebar-toggle-symbol');
    expect(markup).toContain('mask-image');
  });

  it('keeps loaded history mounted and focus-isolated while collapsed', async () => {
    listAgentTasks.mockResolvedValue({
      agentTasks: [{
        id: 'history-task',
        original_prompt: 'Loaded history',
        timestamp: '2026-08-12T19:00:00.000Z',
        status: 'completed',
        result_preview: 'Done',
        file_count: 0,
        follow_up_count: 0,
      }],
      total_count: 1,
      has_more: false,
    });
    const container = document.createElement('div');
    const root = createRoot(container);
    const props = {
      canLoadData: true,
      onToggle: () => {},
      onViewHistoricalAgentTask: () => {},
      onViewAgentTask: () => {},
      onViewScheduledAgentTask: () => {},
      onCreateScheduledAgentTask: () => {},
    };

    try {
      await act(async () => {
        root.render(<Sidebar {...props} isExpanded />);
      });
      await vi.waitFor(() => expect(container.querySelector('.sidebar-row')).not.toBeNull());
      const fetchCount = listAgentTasks.mock.calls.length;

      await act(async () => {
        root.render(<Sidebar {...props} isExpanded={false} />);
      });

      expect(container.querySelector('.sidebar-row')).not.toBeNull();
      expect(container.querySelector('.sidebar-content-layer--expanded')?.hasAttribute('inert')).toBe(true);
      expect(listAgentTasks).toHaveBeenCalledTimes(fetchCount);
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });

  it('re-renders only the row for the agent whose fields actually changed (Package 3 regression)', async () => {
    listAgentTasks.mockResolvedValue({ agentTasks: [], total_count: 0, has_more: false });

    const agentA: AgentState = {
      ...createAgentState('agent-a', 'Summarize the report'),
      status: 'processing',
      currentStep: 'Reading source documents',
    };
    const agentB: AgentState = {
      ...createAgentState('agent-b', 'Draft the follow-up email'),
      status: 'processing',
      currentStep: 'Drafting',
    };
    allAgentsRef.current = [agentA, agentB];
    getAgentMock.mockImplementation((id: string) => allAgentsRef.current.find(a => a.agentTaskId === id));

    const container = document.createElement('div');
    const root = createRoot(container);
    const props = {
      isExpanded: false,
      canLoadData: false,
      onToggle: () => {},
      onViewHistoricalAgentTask: () => {},
      onViewAgentTask: () => {},
      onViewScheduledAgentTask: () => {},
      onCreateScheduledAgentTask: () => {},
    };

    try {
      await act(async () => {
        root.render(<Sidebar {...props} />);
      });

      expect(agentTaskRowRenderCounts.get('agent-a')).toBe(1);
      expect(agentTaskRowRenderCounts.get('agent-b')).toBe(1);

      // Mutate only agent-a's own currentStep, then force Sidebar to
      // re-render (a fresh allAgents array reference simulates the
      // agentStore's real update-notify cycle). agent-b's own object is
      // untouched, so its derived row props stay value-equal.
      allAgentsRef.current = [
        { ...agentA, currentStep: 'Generating summary' },
        agentB,
      ];
      await act(async () => {
        root.render(<Sidebar {...props} onToggle={() => {}} />);
      });

      expect(agentTaskRowRenderCounts.get('agent-a')).toBe(2);
      expect(agentTaskRowRenderCounts.get('agent-b')).toBe(1);
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });

  it('shows an inline delete confirmation (no modal backdrop) for a history row requested via the context menu, and deletes on confirm', async () => {
    listAgentTasks.mockResolvedValue({
      agentTasks: [{
        id: 'history-task-1',
        original_prompt: 'Summarize the quarterly report',
        timestamp: '2026-08-12T19:00:00.000Z',
        status: 'completed',
        result_preview: 'Done',
        file_count: 0,
        follow_up_count: 0,
      }],
      total_count: 1,
      has_more: false,
    });
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      await act(async () => {
        root.render(
          <Sidebar
            isExpanded
            canLoadData
            onToggle={() => {}}
            onViewHistoricalAgentTask={() => {}}
            onViewAgentTask={() => {}}
            onViewScheduledAgentTask={() => {}}
            onCreateScheduledAgentTask={() => {}}
          />,
        );
      });
      await vi.waitFor(() => {
        expect(container.querySelector('.sidebar-row')).not.toBeNull();
      });

      const row = container.querySelector<HTMLElement>('.sidebar-row');
      act(() => {
        row?.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true }));
      });
      await vi.waitFor(() => {
        expect(container.querySelector('.context-menu')).not.toBeNull();
      });

      act(() => {
        container.querySelector<HTMLButtonElement>('.context-menu-item.danger')?.click();
      });

      expect(container.querySelector('.sidebar-row--confirm-delete')).not.toBeNull();
      expect(container.querySelector('.overlay-backdrop')).toBeNull();
      expect(document.body.querySelector('.overlay-backdrop')).toBeNull();

      await act(async () => {
        container.querySelector<HTMLButtonElement>('.sidebar-row-confirm__btn--danger')?.click();
      });

      expect(deleteAgentTask).toHaveBeenCalledWith('history-task-1');
      expect(container.querySelector('.sidebar-row--confirm-delete')).toBeNull();
      expect(container.querySelector('.sidebar-row')).toBeNull();
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });
});
