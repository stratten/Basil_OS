import { render } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useConversationAutoScroll } from './useConversationAutoScroll';

let resizeCallback: (() => void) | undefined;
let frameCallbacks: FrameRequestCallback[] = [];

class FakeResizeObserver {
  constructor(callback: () => void) {
    resizeCallback = callback;
  }
  observe() {}
  disconnect() {}
}

function Harness({ pinned, enabled = true }: { pinned: boolean; enabled?: boolean }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(pinned);
  pinnedRef.current = pinned;
  useConversationAutoScroll(viewportRef, pinnedRef, enabled);
  return (
    <div ref={viewportRef} data-testid="viewport">
      <div>content</div>
    </div>
  );
}

function viewport(container: HTMLElement): HTMLDivElement {
  const element = container.querySelector('[data-testid="viewport"]') as HTMLDivElement;
  Object.defineProperty(element, 'scrollHeight', { configurable: true, value: 900 });
  return element;
}

describe('useConversationAutoScroll', () => {
  beforeEach(() => {
    resizeCallback = undefined;
    frameCallbacks = [];
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameCallbacks.push(callback);
      return frameCallbacks.length;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('follows the bottom when content grows while pinned', () => {
    const { container } = render(<Harness pinned />);
    const element = viewport(container);
    element.scrollTop = 0;

    resizeCallback?.();
    resizeCallback?.();
    expect(frameCallbacks).toHaveLength(1);
    frameCallbacks[0](0);

    expect(element.scrollTop).toBe(900);
  });

  it('leaves the scroll position alone after the user scrolls away', () => {
    const { container } = render(<Harness pinned={false} />);
    const element = viewport(container);
    element.scrollTop = 120;

    resizeCallback?.();
    frameCallbacks[0](0);

    expect(element.scrollTop).toBe(120);
  });

  it('does not observe when disabled', () => {
    render(<Harness pinned enabled={false} />);
    expect(resizeCallback).toBeUndefined();
  });
});
