// @vitest-environment jsdom

import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentState, DisplayableAgentTask } from '../types';
import { WEBKIT_WINDOW_CHROME_FRAME_INSET_PX } from '../../../shared/webkitWindowChrome';
import * as bridge from '../services/bridge';
import { useResultWidgetSizing } from './useResultWidgetSizing';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/bridge', () => ({
  requestResize: vi.fn(),
  reportWidgetHeaderHeight: vi.fn(),
}));

const baseDisplaySource = {
  agentTaskId: 'task-1',
  status: 'completed',
  isStreaming: false,
  result: 'done',
  originalPrompt: '',
  delegatedProviderReportCards: [],
  structuredFiles: [],
  referencePaths: [],
  showWorkflowPlan: false,
  agentTaskHistory: [],
  progressSteps: [],
  executionTimeline: [],
  stepDetails: [],
  checkpointAvailable: false,
  thinkingSegments: [],
} satisfies DisplayableAgentTask;

function SizingHarness({ selectedAgent }: { selectedAgent: AgentState }) {
  useResultWidgetSizing({
    displaySource: selectedAgent,
    selectedAgent,
    viewedDetail: null,
    sidebarExpanded: false,
    embedded: false,
  });
  return null;
}

describe('useResultWidgetSizing checkpoint overlay', () => {
  let container: HTMLDivElement | null = null;
  let root: ReturnType<typeof createRoot> | null = null;

  afterEach(() => {
    if (root) {
      act(() => {
        root?.unmount();
      });
    }
    root = null;
    container?.remove();
    container = null;
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('resizes and remeasures an active checkpoint dialog from its intrinsic height', async () => {
    vi.useFakeTimers();
    const resizeObservers: ResizeObserverCallback[] = [];
    class ResizeObserverStub {
      constructor(callback: ResizeObserverCallback) {
        resizeObservers.push(callback);
      }

      observe(): void {}

      disconnect(): void {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 36 });
    document.body.appendChild(header);
    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 200 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);
    const backdrop = document.createElement('div');
    backdrop.className = 'agent-task-input-backdrop';
    backdrop.style.paddingTop = '20px';
    backdrop.style.paddingBottom = '20px';
    const dialog = document.createElement('section');
    dialog.className = 'agent-task-input-dialog';
    Object.defineProperty(dialog, 'offsetHeight', { configurable: true, value: 248 });
    Object.defineProperty(dialog, 'scrollHeight', { configurable: true, value: 388 });
    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);

    const checkpointAgent: AgentState = Object.assign({}, baseDisplaySource, {
      status: 'processing' as AgentState['status'],
      isStreaming: true,
      hasUnreadResult: false,
      timestamp: '',
      showApprovalPrompt: false,
      approvalRequests: [],
      seenApprovalIds: [],
      rememberApprovalChoice: false,
      showCheckpointPrompt: true,
      inlineCheckpoint: {
        checkpoint_id: 'checkpoint-1',
        prompt: 'Choose an option',
        input_type: 'choice',
      } as NonNullable<AgentState['inlineCheckpoint']>,
    });

    try {
      act(() => {
        root?.render(<SizingHarness selectedAgent={checkpointAgent} />);
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      expect(bridge.requestResize).toHaveBeenCalledWith(
        expect.any(Number),
        36 + 388 + 40 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2,
        'content',
        444,
      );

      vi.mocked(bridge.requestResize).mockClear();
      Object.defineProperty(dialog, 'scrollHeight', { configurable: true, value: 460 });
      act(() => {
        resizeObservers[0]?.([], {} as ResizeObserver);
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      expect(bridge.requestResize).toHaveBeenCalledWith(
        expect.any(Number),
        36 + 460 + 40 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2,
        'content',
        444,
      );
    } finally {
      header.remove();
      contentArea.remove();
      backdrop.remove();
    }
  });
});

function InteractiveOverlayChromeHarness({
  selectedAgent,
  onState,
}: {
  selectedAgent: AgentState;
  onState: (state: { isChromeCollapsed: boolean; handleToggleChromeCollapsed: () => void }) => void;
}) {
  const { isChromeCollapsed, handleToggleChromeCollapsed } = useResultWidgetSizing({
    displaySource: selectedAgent,
    selectedAgent,
    viewedDetail: null,
    sidebarExpanded: false,
    embedded: false,
  });

  useEffect(() => {
    onState({ isChromeCollapsed, handleToggleChromeCollapsed });
  }, [handleToggleChromeCollapsed, isChromeCollapsed, onState]);

  return null;
}

describe('useResultWidgetSizing interactive overlay sizing contract', () => {
  let container: HTMLDivElement | null = null;
  let root: ReturnType<typeof createRoot> | null = null;

  afterEach(() => {
    if (root) {
      act(() => {
        root?.unmount();
      });
    }
    root = null;
    container?.remove();
    container = null;
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("resizes to include an active approval card's intrinsic height and preferred width", async () => {
    vi.useFakeTimers();
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 36 });
    document.body.appendChild(header);
    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 60 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);
    // Stands in for ApprovalOverlay's own `.overlay-card` root, marked the
    // same way the real component marks it: a script-content approval
    // prefers 640px, which the old width branch (a flat 480px for any
    // `showApprovalPrompt` agent, regardless of what the approval actually
    // contains) could never produce -- proving this measurement, not the
    // old state-flag guess, is what drove the resulting width.
    const overlayCard = document.createElement('div');
    overlayCard.className = 'overlay-card';
    overlayCard.setAttribute('data-agent-desk-interactive-overlay', 'true');
    overlayCard.setAttribute('data-preferred-content-width', '640');
    Object.defineProperty(overlayCard, 'offsetHeight', { configurable: true, value: 260 });
    Object.defineProperty(overlayCard, 'scrollHeight', { configurable: true, value: 260 });
    document.body.appendChild(overlayCard);

    const approvalAgent: AgentState = Object.assign({}, baseDisplaySource, {
      status: 'processing' as AgentState['status'],
      isStreaming: true,
      hasUnreadResult: false,
      timestamp: '',
      showApprovalPrompt: true,
      approvalRequests: [],
      seenApprovalIds: [],
      rememberApprovalChoice: false,
      showCheckpointPrompt: false,
    });

    try {
      act(() => {
        root?.render(<SizingHarness selectedAgent={approvalAgent} />);
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      expect(bridge.requestResize).toHaveBeenCalledWith(
        640 + 28,
        36 + 260 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2,
        'content',
        444,
      );
    } finally {
      header.remove();
      contentArea.remove();
      overlayCard.remove();
    }
  });

  it('expands a collapsed desk directly to the measured interactive overlay instead of the stale pre-collapse frame', () => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 40 });
    document.body.appendChild(header);
    // Present in the DOM before the interaction request arrives, exactly
    // like the checkpoint dialog above: the overlay component itself
    // decides when to mount it, this hook only measures whatever is
    // currently marked and visible.
    const overlayCard = document.createElement('div');
    overlayCard.className = 'overlay-card';
    overlayCard.setAttribute('data-agent-desk-interactive-overlay', 'true');
    overlayCard.setAttribute('data-preferred-content-width', '480');
    Object.defineProperty(overlayCard, 'offsetHeight', { configurable: true, value: 300 });
    Object.defineProperty(overlayCard, 'scrollHeight', { configurable: true, value: 300 });
    document.body.appendChild(overlayCard);

    const idleAgent: AgentState = Object.assign({}, baseDisplaySource, {
      status: 'processing' as AgentState['status'],
      isStreaming: true,
      hasUnreadResult: false,
      timestamp: '',
      showApprovalPrompt: false,
      approvalRequests: [],
      seenApprovalIds: [],
      rememberApprovalChoice: false,
      showCheckpointPrompt: false,
    });

    const states: Array<{ isChromeCollapsed: boolean; handleToggleChromeCollapsed: () => void }> = [];
    const onState = (state: typeof states[number]) => states.push(state);

    try {
      act(() => {
        root?.render(<InteractiveOverlayChromeHarness selectedAgent={idleAgent} onState={onState} />);
      });

      // Collapse while idle: this captures the pre-collapse frame
      // (320x180) that the old code path would have simply restored.
      act(() => {
        states[states.length - 1]?.handleToggleChromeCollapsed();
      });
      expect(states[states.length - 1]?.isChromeCollapsed).toBe(true);

      vi.mocked(bridge.requestResize).mockClear();

      // The interaction request arrives while still collapsed: the
      // `needsUserInput` effect fires `expandChrome()` on its own, with no
      // manual toggle involved.
      act(() => {
        root?.render(
          <InteractiveOverlayChromeHarness
            selectedAgent={{ ...idleAgent, showApprovalPrompt: true }}
            onState={onState}
          />,
        );
      });

      expect(states[states.length - 1]?.isChromeCollapsed).toBe(false);
      // 480 (preferred width) + 28 (collapsed sidebar rail) = 508, and
      // 40 (header) + 300 (overlay) + the shared frame inset budget -- both
      // comfortably larger than the stale 320x180 pre-collapse frame, which
      // is exactly what the old "just restore what we had" code produced.
      expect(bridge.requestResize).toHaveBeenCalledWith(
        508,
        40 + 300 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2,
        'expanded',
        444,
      );
    } finally {
      header.remove();
      overlayCard.remove();
    }
  });
});
