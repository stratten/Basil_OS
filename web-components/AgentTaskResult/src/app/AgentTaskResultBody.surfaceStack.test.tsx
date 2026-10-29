// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SurfaceStack } from './AgentTaskResultBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SurfaceStack', () => {
  const animationFrames: FrameRequestCallback[] = [];
  const canceledFrames = new Set<number>();

  beforeEach(() => {
    animationFrames.length = 0;
    canceledFrames.clear();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      animationFrames.push(callback);
      return animationFrames.length;
    });
    vi.stubGlobal('cancelAnimationFrame', (handle: number) => {
      canceledFrames.add(handle);
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function flushFrames() {
    // Mirrors the browser: skip any frame index that was canceled before
    // it ran, exactly like a real cancelAnimationFrame would.
    for (let index = 0; index < animationFrames.length; index += 1) {
      if (!canceledFrames.has(index + 1)) animationFrames[index]?.(0);
    }
    animationFrames.length = 0;
  }

  it('does not animate the very first render', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="empty">idle</SurfaceStack>);
    });

    const layer = container.querySelector('.agent-task-surface-layer') as HTMLElement;
    expect(layer.dataset.presencePhase).toBe('present');
    expect(animationFrames).toHaveLength(0);

    act(() => root.unmount());
  });

  it('reaches the present phase even when the newly-entering surface re-renders with fresh content before its frame runs', () => {
    // Reproduces the reported bug: a brand-new agent task is selected (the
    // surface key changes from "empty" to "agent:1"), and — before the
    // browser gets a chance to service the single requestAnimationFrame
    // that would reveal it — a local model's rapid streaming/progress
    // events cause several more renders under that *same* surface key.
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="empty">idle</SurfaceStack>);
    });

    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1">processing (0 tokens)</SurfaceStack>);
    });
    let entered = container.querySelector('.agent-task-surface-layer:not([data-presence-phase="exiting"])') as HTMLElement;
    expect(entered.dataset.presencePhase).toBe('entering');

    // Same surfaceKey, fresh children -- mimics a burst of WS progress
    // events landing before the entrance frame is serviced. Under the old
    // implementation (effect deps included `children`), each of these
    // re-renders canceled the pending frame via its own cleanup and never
    // rescheduled a replacement, permanently stranding the surface at
    // opacity: 0.
    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1">processing (12 tokens)</SurfaceStack>);
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1">processing (37 tokens)</SurfaceStack>);
    });

    act(() => {
      flushFrames();
    });

    entered = container.querySelector('.agent-task-surface-layer:not([data-presence-phase="exiting"])') as HTMLElement;
    expect(entered.dataset.presencePhase).toBe('present');
    expect(entered.textContent).toBe('processing (37 tokens)');

    act(() => root.unmount());
  });

  it('settles to present from a transitionend event even if the animation frame never fires', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="empty">idle</SurfaceStack>);
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1">processing</SurfaceStack>);
    });

    const entered = container.querySelector('.agent-task-surface-layer:not([data-presence-phase="exiting"])') as HTMLElement;
    expect(entered.dataset.presencePhase).toBe('entering');

    act(() => {
      entered.dispatchEvent(new TransitionEvent('transitionend', {
        bubbles: true,
        propertyName: 'opacity',
      }));
    });

    expect(entered.dataset.presencePhase).toBe('present');

    act(() => root.unmount());
  });

  it('captures the latest content for the outgoing layer, not whatever was current when the key last changed', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1">first result</SurfaceStack>);
    });
    act(() => {
      flushFrames();
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1">updated result</SurfaceStack>);
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:2">second task</SurfaceStack>);
    });

    const outgoing = container.querySelector('[data-presence-phase="exiting"]') as HTMLElement;
    expect(outgoing.textContent).toBe('updated result');

    act(() => root.unmount());
  });
});
