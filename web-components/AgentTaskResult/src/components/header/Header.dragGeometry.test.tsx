// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  reportWidgetHeaderDragGeometry: vi.fn(),
}));

vi.mock('../../services/bridge', () => ({
  closeWidget: vi.fn(),
  minimizeWidget: vi.fn(),
  reportWidgetHeaderDragGeometry: mocks.reportWidgetHeaderDragGeometry,
}));

import Header from './Header';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  mocks.reportWidgetHeaderDragGeometry.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(overrides: Partial<Parameters<typeof Header>[0]> = {}) {
  act(() => {
    root.render(
      <Header
        isProcessing
        isCapturing={false}
        bubbleMode="ambient"
        baseColor="#33559B"
        accentColor="#FFFFFF"
        {...overrides}
      />,
    );
  });
}

describe('Header drag geometry reporting', () => {
  it('tells the native window which part of the header drags it once the header is on screen', () => {
    render({ isCollapsed: true });

    expect(mocks.reportWidgetHeaderDragGeometry).toHaveBeenCalledTimes(1);
    const [height, ranges] = mocks.reportWidgetHeaderDragGeometry.mock.calls[0];
    expect(height).toBe(window.innerHeight);
    expect(Array.isArray(ranges)).toBe(true);
  });

  it('reports again when a run starts and the Pause and Stop buttons join the header', () => {
    const header = () => container.querySelector<HTMLElement>('[data-agent-task-header-bubble]')!;
    render({ isCollapsed: true });
    header().getBoundingClientRect = () => ({ right: 292 } as DOMRect);
    mocks.reportWidgetHeaderDragGeometry.mockClear();

    render({
      isCollapsed: true,
      showCancelStop: true,
      onCancelRunning: vi.fn(),
      runPauseState: 'running',
      onPauseRunning: vi.fn(),
      onResumeRunning: vi.fn(),
    });

    expect(mocks.reportWidgetHeaderDragGeometry).toHaveBeenCalledTimes(1);
    const [, ranges] = mocks.reportWidgetHeaderDragGeometry.mock.calls[0];
    expect(ranges).toContainEqual({ start: 190, end: 248 });
  });

  it('does not report for the embedded toolbar, which is not a movable window', () => {
    render({ embedded: true });

    expect(mocks.reportWidgetHeaderDragGeometry).not.toHaveBeenCalled();
  });
});
