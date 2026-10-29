// @vitest-environment jsdom

import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import { useResultWidgetSizing } from './useResultWidgetSizing';
import * as bridge from '../services/bridge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/bridge', () => ({
  requestResize: vi.fn(),
  reportWidgetHeaderHeight: vi.fn(),
}));

// A task in progress takes the measuring path; a finished one skips it and already reads the real window.
const liveTask = {
  agentTaskId: 'task-1',
  status: 'processing',
  isStreaming: true,
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

interface SizingControls {
  handleToggleChromeCollapsed: () => void;
}

function Harness({ sidebar, tray, controls }: { sidebar: boolean; tray: boolean; controls: { current: SizingControls | null } }) {
  const sizing = useResultWidgetSizing({
    displaySource: liveTask,
    selectedAgent: null,
    viewedDetail: liveTask,
    sidebarExpanded: sidebar,
    embedded: false,
  });
  useEffect(() => {
    sizing.setDetailTrayOpen(tray);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tray]);
  controls.current = sizing;
  return null;
}

let container: HTMLDivElement;
let root: Root;
let header: HTMLElement;
let contentArea: HTMLElement;
const controls: { current: SizingControls | null } = { current: null };

function setWindowWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
}

async function settle() {
  await act(async () => {
    vi.runAllTimers();
    await Promise.resolve();
  });
}

async function renderLayout(sidebar: boolean, tray: boolean) {
  act(() => root.render(<Harness sidebar={sidebar} tray={tray} controls={controls} />));
  await settle();
}

function requestedWidths(): number[] {
  return vi.mocked(bridge.requestResize).mock.calls.map(call => call[0] as number);
}

describe('useResultWidgetSizing after the user resizes the window', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 700 });
    header = document.createElement('header');
    header.className = 'widget-header';
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 52 });
    document.body.appendChild(header);
    contentArea = document.createElement('div');
    contentArea.className = 'content-area';
    const mainContent = document.createElement('div');
    mainContent.className = 'main-content';
    Object.defineProperty(mainContent, 'offsetHeight', { configurable: true, value: 200 });
    contentArea.appendChild(mainContent);
    document.body.appendChild(contentArea);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    header.remove();
    contentArea.remove();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('does not snap a shrunken window back to its earlier size when the tray or sidebar toggles', async () => {
    setWindowWidth(2000);
    await renderLayout(false, true);
    await renderLayout(true, true);
    expect(requestedWidths().every(width => width === 2000)).toBe(true);

    setWindowWidth(1100);
    vi.mocked(bridge.requestResize).mockClear();
    await renderLayout(true, false);
    expect(requestedWidths().length).toBeGreaterThan(0);
    expect(requestedWidths().every(width => width === 1100)).toBe(true);

    vi.mocked(bridge.requestResize).mockClear();
    await renderLayout(false, false);
    expect(requestedWidths().every(width => width === 1100)).toBe(true);

    vi.mocked(bridge.requestResize).mockClear();
    await renderLayout(true, false);
    expect(requestedWidths().every(width => width === 1100)).toBe(true);
  });

  it('asks for more width only when the window is narrower than the new layout minimum', async () => {
    setWindowWidth(700);
    await renderLayout(false, false);
    vi.mocked(bridge.requestResize).mockClear();
    await renderLayout(true, true);

    const widths = requestedWidths();
    expect(widths.length).toBeGreaterThan(0);
    expect(Math.max(...widths)).toBeGreaterThanOrEqual(872);
    expect(vi.mocked(bridge.requestResize)).toHaveBeenCalledWith(expect.any(Number), expect.any(Number), 'layout', 872);
  });

  it('stops holding the pre-collapse width once the window has been expanded again', async () => {
    setWindowWidth(1500);
    await renderLayout(false, false);

    act(() => controls.current?.handleToggleChromeCollapsed());
    await act(async () => {
      vi.advanceTimersByTime(50);
      await Promise.resolve();
    });
    await settle();
    act(() => controls.current?.handleToggleChromeCollapsed());
    await act(async () => {
      vi.advanceTimersByTime(50);
      await Promise.resolve();
    });
    await settle();

    setWindowWidth(1000);
    vi.mocked(bridge.requestResize).mockClear();
    await renderLayout(false, true);

    expect(requestedWidths().length).toBeGreaterThan(0);
    expect(requestedWidths().every(width => width <= 1000)).toBe(true);
  });
});
