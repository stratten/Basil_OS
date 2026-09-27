// @vitest-environment jsdom

import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentState, DisplayableAgentTask } from '../types';
import { useResultWidgetSizing } from './useResultWidgetSizing';
import { WEBKIT_WINDOW_CHROME_FRAME_INSET_PX } from '../../../shared/webkitWindowChrome';
import { DETAIL_TRAY_MIN_WIDTH } from './detailTraySizing';
import * as bridge from '../services/bridge';

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

function SizingHarness({
  embedded,
  displaySource,
  selectedAgent = null,
  openDetailTray,
  detailTrayWidth,
  useDisplaySourceForSizing = false,
  sidebarExpanded = false,
  contentSurfaceMode,
  trayResizing,
  onSetTrayResizing,
}: {
  embedded: boolean;
  displaySource: DisplayableAgentTask | null;
  selectedAgent?: AgentState | null;
  openDetailTray?: boolean;
  detailTrayWidth?: number;
  useDisplaySourceForSizing?: boolean;
  sidebarExpanded?: boolean;
  contentSurfaceMode?: 'agent' | 'detached' | 'empty' | 'scheduled';
  trayResizing?: boolean;
  onSetTrayResizing?: (setTrayResizing: (isResizing: boolean) => void) => void;
}) {
  const { setDetailTrayOpen, setDetailTrayWidth, setTrayResizing } = useResultWidgetSizing({
    displaySource,
    selectedAgent,
    viewedDetail: useDisplaySourceForSizing ? displaySource : null,
    sidebarExpanded,
    embedded,
    contentSurfaceMode,
  });
  useEffect(() => {
    if (openDetailTray !== undefined) setDetailTrayOpen(openDetailTray);
    if (detailTrayWidth !== undefined) setDetailTrayWidth(detailTrayWidth);
  }, [detailTrayWidth, openDetailTray, setDetailTrayOpen, setDetailTrayWidth]);
  useEffect(() => {
    onSetTrayResizing?.(setTrayResizing);
  }, [onSetTrayResizing, setTrayResizing]);
  useEffect(() => {
    if (trayResizing !== undefined) setTrayResizing(trayResizing);
  }, [trayResizing, setTrayResizing]);
  return null;
}

function EmptySurfaceChromeHarness({
  onState,
}: {
  onState: (state: {
    isChromeCollapsed: boolean;
    handleToggleChromeCollapsed: () => void;
  }) => void;
}) {
  const { isChromeCollapsed, handleToggleChromeCollapsed } = useResultWidgetSizing({
    displaySource: null,
    selectedAgent: null,
    viewedDetail: null,
    sidebarExpanded: false,
    embedded: false,
    contentSurfaceMode: 'empty',
  });

  useEffect(() => {
    onState({ isChromeCollapsed, handleToggleChromeCollapsed });
  }, [handleToggleChromeCollapsed, isChromeCollapsed, onState]);

  return null;
}

function DetailTrayModeHarness({
  mode,
  width,
}: {
  mode: 'overview' | 'detail' | 'preview';
  width?: number;
}) {
  const {
    detailTrayMode,
    detailTrayWidth,
    openDetailTray,
    setDetailTrayWidth,
  } = useResultWidgetSizing({
    displaySource: baseDisplaySource,
    selectedAgent: null,
    viewedDetail: null,
    sidebarExpanded: false,
    embedded: true,
  });
  useEffect(() => {
    if (width !== undefined) setDetailTrayWidth(width);
    openDetailTray(mode);
  }, [mode, openDetailTray, setDetailTrayWidth, width]);
  return <output>{`${detailTrayMode}:${detailTrayWidth}`}</output>;
}

function ChromeStateHarness({
  displaySource,
  onState,
}: {
  displaySource: DisplayableAgentTask;
  onState: (state: {
    isChromeCollapsed: boolean;
    handleToggleChromeCollapsed: () => void;
    expandChrome: () => void;
  }) => void;
}) {
  const {
    isChromeCollapsed,
    handleToggleChromeCollapsed,
    expandChrome,
  } = useResultWidgetSizing({
    displaySource,
    selectedAgent: null,
    viewedDetail: null,
    sidebarExpanded: false,
    embedded: false,
  });

  useEffect(() => {
    onState({ isChromeCollapsed, handleToggleChromeCollapsed, expandChrome });
  }, [expandChrome, handleToggleChromeCollapsed, isChromeCollapsed, onState]);

  return null;
}

describe('useResultWidgetSizing task-chain collapse state', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('keeps the compact chrome for a follow-up but resets it for another root task', () => {
    const states: Array<{
      isChromeCollapsed: boolean;
      handleToggleChromeCollapsed: () => void;
      expandChrome: () => void;
    }> = [];
    const onState = (state: typeof states[number]) => states.push(state);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root.render(<ChromeStateHarness displaySource={baseDisplaySource} onState={onState} />);
    });
    act(() => {
      states[states.length - 1]?.handleToggleChromeCollapsed();
    });
    expect(states[states.length - 1]?.isChromeCollapsed).toBe(true);

    vi.mocked(bridge.requestResize).mockClear();
    act(() => {
      root.render(
        <ChromeStateHarness
          displaySource={{
            ...baseDisplaySource,
            agentTaskId: 'follow-up-1',
            rootTaskId: 'task-1',
          }}
          onState={onState}
        />,
      );
    });

    expect(states[states.length - 1]?.isChromeCollapsed).toBe(true);
    expect(
      vi.mocked(bridge.requestResize).mock.calls.some(([, , intent]) => intent === 'expanded'),
    ).toBe(false);

    act(() => {
      root.render(
        <ChromeStateHarness
          displaySource={{ ...baseDisplaySource, agentTaskId: 'task-2' }}
          onState={onState}
        />,
      );
    });

    expect(states[states.length - 1]?.isChromeCollapsed).toBe(false);
  });

  it('keeps the detail tray open (and its mode untouched) through a collapse/expand cycle', () => {
    function TrayAndChromeHarness({
      onState,
    }: {
      onState: (state: {
        isChromeCollapsed: boolean;
        detailTrayOpen: boolean;
        detailTrayMode: string;
        handleToggleChromeCollapsed: () => void;
        openDetailTray: (mode: 'overview' | 'detail' | 'preview') => void;
      }) => void;
    }) {
      const {
        isChromeCollapsed,
        detailTrayOpen,
        detailTrayMode,
        handleToggleChromeCollapsed,
        openDetailTray,
      } = useResultWidgetSizing({
        displaySource: baseDisplaySource,
        selectedAgent: null,
        viewedDetail: null,
        sidebarExpanded: false,
        embedded: false,
      });

      useEffect(() => {
        onState({ isChromeCollapsed, detailTrayOpen, detailTrayMode, handleToggleChromeCollapsed, openDetailTray });
      }, [detailTrayMode, detailTrayOpen, handleToggleChromeCollapsed, isChromeCollapsed, onState, openDetailTray]);

      return null;
    }

    const states: Array<{
      isChromeCollapsed: boolean;
      detailTrayOpen: boolean;
      detailTrayMode: string;
      handleToggleChromeCollapsed: () => void;
      openDetailTray: (mode: 'overview' | 'detail' | 'preview') => void;
    }> = [];
    const onState = (state: typeof states[number]) => states.push(state);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root.render(<TrayAndChromeHarness onState={onState} />);
    });

    // Opening in 'detail' mode stands in for "a specific thing is being
    // shown" (a step detail, a file preview, etc.) -- AgentTaskDetailSurface
    // keeps its own more granular selection (artifactPreviewId, etc.)
    // mounted for as long as this hook's detailTrayOpen stays true, so
    // proving the mode survives collapse/expand here is the load-bearing
    // guarantee for "whatever was displayed comes back untouched".
    act(() => {
      states[states.length - 1]?.openDetailTray('detail');
    });
    expect(states[states.length - 1]?.detailTrayOpen).toBe(true);
    expect(states[states.length - 1]?.detailTrayMode).toBe('detail');

    act(() => {
      states[states.length - 1]?.handleToggleChromeCollapsed();
    });
    expect(states[states.length - 1]?.isChromeCollapsed).toBe(true);
    // The tray must stay logically open while collapsed: ExecutionDetailTray
    // only unmounts (discarding what it was showing) when isOpen is false,
    // and the compact window already fully hides it visually via
    // widget-body's hidden/inert attributes, so there is nothing left for
    // forcing this flag closed to accomplish.
    expect(states[states.length - 1]?.detailTrayOpen).toBe(true);
    expect(states[states.length - 1]?.detailTrayMode).toBe('detail');

    act(() => {
      states[states.length - 1]?.handleToggleChromeCollapsed();
    });
    expect(states[states.length - 1]?.isChromeCollapsed).toBe(false);
    expect(states[states.length - 1]?.detailTrayOpen).toBe(true);
    expect(states[states.length - 1]?.detailTrayMode).toBe('detail');
  });

  it('does not reopen the detail tray after collapse/expand if it was already closed', () => {
    function TrayAndChromeHarness({
      onState,
    }: {
      onState: (state: {
        isChromeCollapsed: boolean;
        detailTrayOpen: boolean;
        handleToggleChromeCollapsed: () => void;
      }) => void;
    }) {
      const {
        isChromeCollapsed,
        detailTrayOpen,
        handleToggleChromeCollapsed,
      } = useResultWidgetSizing({
        displaySource: baseDisplaySource,
        selectedAgent: null,
        viewedDetail: null,
        sidebarExpanded: false,
        embedded: false,
      });

      useEffect(() => {
        onState({ isChromeCollapsed, detailTrayOpen, handleToggleChromeCollapsed });
      }, [detailTrayOpen, handleToggleChromeCollapsed, isChromeCollapsed, onState]);

      return null;
    }

    const states: Array<{
      isChromeCollapsed: boolean;
      detailTrayOpen: boolean;
      handleToggleChromeCollapsed: () => void;
    }> = [];
    const onState = (state: typeof states[number]) => states.push(state);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root.render(<TrayAndChromeHarness onState={onState} />);
    });

    act(() => {
      states[states.length - 1]?.handleToggleChromeCollapsed();
    });
    expect(states[states.length - 1]?.isChromeCollapsed).toBe(true);

    act(() => {
      states[states.length - 1]?.handleToggleChromeCollapsed();
    });
    expect(states[states.length - 1]?.isChromeCollapsed).toBe(false);
    expect(states[states.length - 1]?.detailTrayOpen).toBe(false);
  });
});

describe('useResultWidgetSizing embedded mode', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  afterEach(() => {
    vi.clearAllMocks();
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('does not call requestResize when embedded across mount, update, and unmount', () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root.render(<SizingHarness embedded={true} displaySource={baseDisplaySource} />);
    });

    act(() => {
      root.render(
        <SizingHarness
          embedded={true}
          displaySource={{ ...baseDisplaySource, agentTaskId: 'task-2', result: 'updated' }}
        />
      );
    });

    expect(bridge.requestResize).not.toHaveBeenCalled();

    act(() => {
      root.unmount();
    });

    expect(bridge.requestResize).not.toHaveBeenCalled();
  });

  it('uses automatic mode widths until the user resizes the drawer', () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root.render(<DetailTrayModeHarness mode="overview" />);
    });
    expect(container.textContent).toBe('overview:280');

    act(() => {
      root.render(<DetailTrayModeHarness mode="preview" />);
    });
    expect(container.textContent).toBe('preview:400');

    act(() => {
      root.render(<DetailTrayModeHarness mode="detail" width={360} />);
    });
    expect(container.textContent).toBe('detail:360');

    act(() => {
      root.render(<DetailTrayModeHarness mode="preview" />);
    });
    expect(container.textContent).toBe('preview:360');
  });
});

describe('useResultWidgetSizing non-embedded mode', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  afterEach(() => {
    vi.clearAllMocks();
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('does not resize the empty history surface after its expanded sidebar initializes', () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root.render(
        <SizingHarness
          embedded={false}
          displaySource={null}
          sidebarExpanded={true}
          contentSurfaceMode="empty"
        />,
      );
    });

    expect(bridge.requestResize).not.toHaveBeenCalled();
  });

  it('still shrinks the native window when the chrome is collapsed before any task is selected', () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});

    const states: Array<{ isChromeCollapsed: boolean; handleToggleChromeCollapsed: () => void }> = [];
    const onState = (state: typeof states[number]) => states.push(state);

    act(() => {
      root.render(<EmptySurfaceChromeHarness onState={onState} />);
    });
    expect(bridge.requestResize).not.toHaveBeenCalled();

    act(() => {
      states[states.length - 1]?.handleToggleChromeCollapsed();
    });

    expect(states[states.length - 1]?.isChromeCollapsed).toBe(true);
    expect(bridge.requestResize).toHaveBeenCalledWith(300, 78, 'collapsed');

    vi.unstubAllGlobals();
  });

  it('lowers a closed sidebar minimum without shrinking the skipped completed-task frame', () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 636 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 500 });

    act(() => {
      root.render(
        <SizingHarness
          embedded={false}
          displaySource={baseDisplaySource}
          sidebarExpanded
          useDisplaySourceForSizing
        />,
      );
    });
    expect(bridge.requestResize).not.toHaveBeenCalled();

    act(() => {
      root.render(
        <SizingHarness
          embedded={false}
          displaySource={baseDisplaySource}
          sidebarExpanded={false}
          useDisplaySourceForSizing
        />,
      );
    });

    expect(bridge.requestResize).toHaveBeenCalledWith(636, 500, 'layout', 444);
  });

  it('reserves the collapsed rail before the drawer is expanded', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });

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

    try {
      const processingSource = {
        ...baseDisplaySource,
        status: 'processing',
        isStreaming: true,
        result: '',
      };
      act(() => {
        root.render(<SizingHarness embedded={false} displaySource={processingSource} openDetailTray={false} useDisplaySourceForSizing />);
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      expect(bridge.requestResize).toHaveBeenCalledWith(444, expect.any(Number), 'content', 444);

      vi.mocked(bridge.requestResize).mockClear();
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={baseDisplaySource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      expect(bridge.requestResize).toHaveBeenCalledWith(
        400 + DETAIL_TRAY_MIN_WIDTH,
        expect.any(Number),
        'layout',
        400 + DETAIL_TRAY_MIN_WIDTH,
      );

      vi.mocked(bridge.requestResize).mockClear();
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={baseDisplaySource}
            openDetailTray
            detailTrayWidth={600}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      expect(bridge.requestResize).toHaveBeenCalledWith(
        1000,
        expect.any(Number),
        'content',
        1000,
      );
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });

  it('grows a newly selected historical task enough to show the rail', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 300 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 560 });

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

    try {
      act(() => {
        root.render(<SizingHarness embedded={false} displaySource={null} sidebarExpanded />);
      });
      vi.mocked(bridge.requestResize).mockClear();

      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={baseDisplaySource}
            sidebarExpanded
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).toHaveBeenCalledWith(560 + 220, expect.any(Number), 'content', 636);
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });

  it('includes the shared frame inset budget in measured resize height', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });

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

    act(() => {
      root.render(
        <SizingHarness
          embedded={false}
          displaySource={{ ...baseDisplaySource, status: 'running', isStreaming: true, result: 'working' }}
        />,
      );
    });

    await act(async () => {
      vi.runAllTimers();
      await Promise.resolve();
    });

    const expectedHeight = 36 + 200 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2;
    expect(bridge.requestResize).toHaveBeenCalled();
    expect(bridge.requestResize).toHaveBeenCalledWith(
      expect.any(Number),
      expectedHeight,
      'content',
        444,
    );

    header.remove();
    contentArea.remove();
    vi.useRealTimers();
  });

  it('does not measure or bridge-resize after a timeline-only update', async () => {
    vi.useFakeTimers();
    const consoleLog = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 400 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 348 });

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 36 });
    document.body.appendChild(header);

    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 132 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);

    try {
      const runningDisplaySource: DisplayableAgentTask = structuredClone(baseDisplaySource);
      runningDisplaySource.status = 'processing';
      runningDisplaySource.isStreaming = true;

      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={runningDisplaySource}
          />,
        );
      });

      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      consoleLog.mockClear();
      vi.mocked(bridge.requestResize).mockClear();

      const timelineOnlyUpdate: DisplayableAgentTask = structuredClone(runningDisplaySource);
      timelineOnlyUpdate.executionTimeline = [
        {
          type: 'step',
          timestamp: '2026-08-07T19:56:22.356255+00:00',
          content: 'Agent requested user input',
        },
      ];

      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={timelineOnlyUpdate}
          />,
        );
      });

      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(consoleLog).not.toHaveBeenCalled();
      expect(bridge.requestResize).not.toHaveBeenCalled();
    } finally {
      header.remove();
      contentArea.remove();
      consoleLog.mockRestore();
      vi.useRealTimers();
    }
  });

  it('resizes after an observed layout-height change without a state-signature change', async () => {
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
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });

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

    try {
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={{ ...baseDisplaySource, status: 'processing', isStreaming: true }}
          />,
        );
      });

      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      vi.mocked(bridge.requestResize).mockClear();
      Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 260 });

      act(() => {
        resizeObservers[0]?.([], {} as ResizeObserver);
      });

      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).toHaveBeenCalledWith(
        expect.any(Number),
        36 + 260 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2,
        'content',
        444,
      );
    } finally {
      header.remove();
      contentArea.remove();
      vi.unstubAllGlobals();
      vi.useRealTimers();
    }
  });

  it('remeasures when an inline checkpoint adds laid-out content', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 180 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });

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

    try {
      const activeAgent: AgentState = {
        ...baseDisplaySource,
        status: 'processing',
        isStreaming: true,
        hasUnreadResult: false,
        timestamp: '',
        showApprovalPrompt: false,
        approvalRequests: [],
        seenApprovalIds: [],
        rememberApprovalChoice: false,
        showCheckpointPrompt: false,
      };

      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={activeAgent}
            selectedAgent={activeAgent}
          />,
        );
      });

      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      vi.mocked(bridge.requestResize).mockClear();
      Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 260 });
      const checkpointAgent: AgentState = {
        ...activeAgent,
        inlineCheckpoint: {
          checkpoint_id: 'checkpoint-1',
          prompt: 'Choose an option',
          input_type: 'choice',
        },
      };

      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={checkpointAgent}
            selectedAgent={checkpointAgent}
          />,
        );
      });

      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).toHaveBeenCalledWith(
        expect.any(Number),
        36 + 260 + WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2,
        'content',
        444,
      );
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });

  it('does not request a narrower width after manual window growth or sidebar expansion', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 500 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 980 });

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 52 });
    document.body.appendChild(header);
    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 200 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);

    try {
      const processingSource = { ...baseDisplaySource, status: 'processing', isStreaming: true };
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      vi.mocked(bridge.requestResize).mockClear();
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH}
            useDisplaySourceForSizing
            sidebarExpanded
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      const requestedWidths = vi.mocked(bridge.requestResize).mock.calls.map(call => call[0] as number);
      expect(requestedWidths.every(width => width >= 980)).toBe(true);
      expect(bridge.requestResize).toHaveBeenCalledWith(980, 500, 'layout', 872);

      vi.mocked(bridge.requestResize).mockClear();
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray={false}
            useDisplaySourceForSizing
            sidebarExpanded={false}
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      const closingRequestedWidths = vi.mocked(bridge.requestResize).mock.calls.map(call => call[0] as number);
      expect(closingRequestedWidths.every(width => width >= 980)).toBe(true);
      expect(bridge.requestResize).toHaveBeenCalledWith(980, 500, 'layout', 444);
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });

  it('ignores a smaller automatic content resize than the current window width', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 500 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900 });

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 52 });
    document.body.appendChild(header);
    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 120 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);

    try {
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={{ ...baseDisplaySource, status: 'completed', isStreaming: false }}
            openDetailTray={false}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      vi.mocked(bridge.requestResize).mockClear();
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={{ ...baseDisplaySource, status: 'completed', isStreaming: false }}
            openDetailTray={false}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).not.toHaveBeenCalled();
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });

  it('suppresses native window resize while a detail tray resize drag is active, then resizes once on release', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 500 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900 });

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 52 });
    document.body.appendChild(header);
    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 200 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);

    try {
      const processingSource = { ...baseDisplaySource, status: 'processing', isStreaming: true };
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      // Simulate the resize handle's pointermove handler: mark a drag as
      // active, then keep widening the tray the way a live drag does. None
      // of these width changes should reach the native bridge while the
      // drag is in progress -- that is the animated `NSWindow.setFrame`
      // that corrupts WebKit's pointer capture mid-gesture.
      vi.mocked(bridge.requestResize).mockClear();
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH}
            useDisplaySourceForSizing
            trayResizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH + 700}
            useDisplaySourceForSizing
            trayResizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).not.toHaveBeenCalled();

      // Release the drag at the settled width: exactly one resize should
      // now fire, catching the window up to the tray's final width.
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={processingSource}
            openDetailTray
            detailTrayWidth={DETAIL_TRAY_MIN_WIDTH + 700}
            useDisplaySourceForSizing
            trayResizing={false}
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).toHaveBeenCalledTimes(1);
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });

  it('reports the real header height to the native drag area even when the first selection skips the window-resize measurement', async () => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 500 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900 });

    const header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 52 });
    document.body.appendChild(header);
    const contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 120 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);

    try {
      // A completed, non-streaming task selected for the first time takes
      // the skip-measurement path (see the preceding test) and never
      // reaches `measureAndResize`. The drag-area height report must not
      // depend on that path running, or the native drag strip keeps its
      // pre-layout guess until some unrelated later state change happens
      // to un-skip it -- which is the tray-resize-collapses-on-first-open
      // regression this test guards against.
      act(() => {
        root.render(
          <SizingHarness
            embedded={false}
            displaySource={{ ...baseDisplaySource, status: 'completed', isStreaming: false }}
            openDetailTray={false}
            useDisplaySourceForSizing
          />,
        );
      });
      await act(async () => {
        vi.runAllTimers();
        await Promise.resolve();
      });

      expect(bridge.requestResize).not.toHaveBeenCalled();
      expect(bridge.reportWidgetHeaderHeight).toHaveBeenCalledWith(52);
    } finally {
      header.remove();
      contentArea.remove();
      vi.useRealTimers();
    }
  });
});
