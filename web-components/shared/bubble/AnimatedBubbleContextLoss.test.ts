// @vitest-environment jsdom

import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const createRenderer = vi.hoisted(() => vi.fn());

vi.mock('./bubbleRenderer', () => ({ BubbleRenderer: { create: createRenderer } }));

import AnimatedBubble from './AnimatedBubble';

describe('AnimatedBubble graphics context loss', () => {
  let container: HTMLDivElement;
  let root: Root;
  let disposeCount: number;

  beforeEach(() => {
    disposeCount = 0;
    createRenderer.mockReset();
    createRenderer.mockImplementation(() => ({ resize: vi.fn(), draw: vi.fn(), dispose: () => { disposeCount += 1; } }));
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  function mountBubble(): HTMLCanvasElement {
    act(() => {
      root.render(createElement(AnimatedBubble, { size: 40, mode: 'processing', baseColor: 'rgb(0, 0, 255)', accentColor: 'rgb(255, 255, 255)' }));
    });
    return container.querySelector('canvas') as HTMLCanvasElement;
  }

  it('cancels the loss event so the browser is allowed to restore the context', () => {
    const canvas = mountBubble();
    const lost = new Event('webglcontextlost', { cancelable: true });
    canvas.dispatchEvent(lost);
    expect(lost.defaultPrevented).toBe(true);
  });

  it('builds a new renderer when the context is restored, and releases the old one', () => {
    const canvas = mountBubble();
    expect(createRenderer).toHaveBeenCalledTimes(1);
    act(() => {
      canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }));
      canvas.dispatchEvent(new Event('webglcontextrestored'));
    });
    expect(createRenderer).toHaveBeenCalledTimes(2);
    expect(disposeCount).toBe(1);
  });

  it('retries after a restore when no renderer could be created while the context was gone', () => {
    createRenderer.mockReset();
    createRenderer.mockImplementationOnce(() => null);
    createRenderer.mockImplementation(() => ({ resize: vi.fn(), draw: vi.fn(), dispose: () => { disposeCount += 1; } }));
    const canvas = mountBubble();
    expect(createRenderer).toHaveBeenCalledTimes(1);
    act(() => {
      canvas.dispatchEvent(new Event('webglcontextrestored'));
    });
    expect(createRenderer).toHaveBeenCalledTimes(2);
  });

  it('stops listening once unmounted', () => {
    const canvas = mountBubble();
    act(() => root.render(null));
    const lost = new Event('webglcontextlost', { cancelable: true });
    canvas.dispatchEvent(lost);
    expect(lost.defaultPrevented).toBe(false);
    act(() => {
      canvas.dispatchEvent(new Event('webglcontextrestored'));
    });
    expect(createRenderer).toHaveBeenCalledTimes(1);
  });
});
