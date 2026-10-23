// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import type { ArtifactPreviewTransport } from './transport/artifactPreviewTransport';
import { useNativeArtifactPreviewSlot } from './useNativeArtifactPreviewSlot';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function createTransportMocks(): ArtifactPreviewTransport & {
  setInlineNativePreviewFrame: Mock<ArtifactPreviewTransport['setInlineNativePreviewFrame']>;
  hideInlineNativePreview: Mock<ArtifactPreviewTransport['hideInlineNativePreview']>;
  clearInlineNativePreview: Mock<ArtifactPreviewTransport['clearInlineNativePreview']>;
} {
  return {
    previewFile: vi.fn(),
    clearFilePreview: vi.fn(),
    registerFilePreviewUpdateHandler: vi.fn().mockReturnValue(() => {}),
    setInlineNativePreviewFrame: vi.fn<ArtifactPreviewTransport['setInlineNativePreviewFrame']>(),
    hideInlineNativePreview: vi.fn<ArtifactPreviewTransport['hideInlineNativePreview']>(),
    clearInlineNativePreview: vi.fn<ArtifactPreviewTransport['clearInlineNativePreview']>(),
  };
}

let bridgeMocks = createTransportMocks();

let currentRect = new DOMRect(12, 24, 320, 180);
let resizeCallback: ResizeObserverCallback | undefined;

class TestResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback;
  }

  observe() {}
  disconnect() {}
  unobserve() {}
}

function PreviewSlot({ requestId, enabled }: { requestId?: string; enabled: boolean }) {
  const ref = useNativeArtifactPreviewSlot({ requestId, enabled, transport: bridgeMocks });
  return <div ref={ref} data-testid="native-slot" />;
}

describe('useNativeArtifactPreviewSlot', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let originalRect: typeof HTMLElement.prototype.getBoundingClientRect;
  let originalResizeObserver: typeof ResizeObserver;
  let originalInnerWidth: number;
  let originalInnerHeight: number;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    currentRect = new DOMRect(12, 24, 320, 180);
    originalRect = HTMLElement.prototype.getBoundingClientRect;
    originalResizeObserver = globalThis.ResizeObserver;
    originalInnerWidth = window.innerWidth;
    originalInnerHeight = window.innerHeight;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 768 });
    HTMLElement.prototype.getBoundingClientRect = () => currentRect;
    globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
    bridgeMocks = createTransportMocks();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    HTMLElement.prototype.getBoundingClientRect = originalRect;
    globalThis.ResizeObserver = originalResizeObserver;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalInnerWidth });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalInnerHeight });
    vi.useRealTimers();
  });

  function flushAnimationFrame() {
    act(() => {
      vi.advanceTimersByTime(17);
    });
  }

  it('reports one visible finite frame and suppresses an unchanged resize', () => {
    act(() => root.render(<PreviewSlot enabled requestId="pdf-a" />));

    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledWith('pdf-a', {
      left: 12,
      top: 24,
      width: 320,
      height: 180,
      viewportWidth: 1024,
      viewportHeight: 768,
    });

    act(() => resizeCallback?.([], {} as ResizeObserver));
    flushAnimationFrame();

    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledTimes(1);
  });

  it('reports new geometry after a resize and a captured nested scroll', () => {
    act(() => root.render(<PreviewSlot enabled requestId="pdf-a" />));
    currentRect = new DOMRect(16, 36, 300, 220);

    act(() => resizeCallback?.([], {} as ResizeObserver));
    flushAnimationFrame();
    document.dispatchEvent(new Event('scroll', { bubbles: true }));
    flushAnimationFrame();

    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenLastCalledWith('pdf-a', {
      left: 16,
      top: 36,
      width: 300,
      height: 220,
      viewportWidth: 1024,
      viewportHeight: 768,
    });
    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledTimes(2);
  });

  it('clears only the superseded request when selection changes', () => {
    act(() => root.render(<PreviewSlot enabled requestId="pdf-a" />));
    act(() => root.render(<PreviewSlot enabled requestId="pdf-b" />));

    expect(bridgeMocks.clearInlineNativePreview).toHaveBeenCalledWith('pdf-a');
    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenLastCalledWith('pdf-b', expect.any(Object));
    expect(bridgeMocks.clearInlineNativePreview).not.toHaveBeenCalledWith('pdf-b');
  });

  it('clears the active request on unmount', () => {
    act(() => root.render(<PreviewSlot enabled requestId="pdf-a" />));
    act(() => root.unmount());

    expect(bridgeMocks.clearInlineNativePreview).toHaveBeenCalledWith('pdf-a');
  });

  it('hides an offscreen request without sending an offscreen frame and remounts it when visible', () => {
    currentRect = new DOMRect(0, 900, 320, 180);
    act(() => root.render(<PreviewSlot enabled requestId="pdf-a" />));

    expect(bridgeMocks.setInlineNativePreviewFrame).not.toHaveBeenCalled();
    expect(bridgeMocks.hideInlineNativePreview).toHaveBeenCalledWith('pdf-a');
    expect(bridgeMocks.clearInlineNativePreview).not.toHaveBeenCalled();

    currentRect = new DOMRect(0, 24, 320, 180);
    document.dispatchEvent(new Event('scroll', { bubbles: true }));
    flushAnimationFrame();

    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledWith('pdf-a', {
      left: 0,
      top: 24,
      width: 320,
      height: 180,
      viewportWidth: 1024,
      viewportHeight: 768,
    });
  });

  it('does not report or clear when disabled', () => {
    act(() => root.render(<PreviewSlot enabled={false} requestId="pdf-a" />));

    expect(bridgeMocks.setInlineNativePreviewFrame).not.toHaveBeenCalled();
    expect(bridgeMocks.clearInlineNativePreview).not.toHaveBeenCalled();
  });

  it('reports updated tray geometry after a resize without duplicate unchanged frames', () => {
    act(() => root.render(<PreviewSlot enabled requestId="pdf-a" />));
    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledTimes(1);

    currentRect = new DOMRect(12, 24, 420, 360);
    act(() => resizeCallback?.([], {} as ResizeObserver));
    flushAnimationFrame();

    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenLastCalledWith('pdf-a', {
      left: 12,
      top: 24,
      width: 420,
      height: 360,
      viewportWidth: 1024,
      viewportHeight: 768,
    });
    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledTimes(2);

    act(() => resizeCallback?.([], {} as ResizeObserver));
    flushAnimationFrame();
    expect(bridgeMocks.setInlineNativePreviewFrame).toHaveBeenCalledTimes(2);
  });
});
