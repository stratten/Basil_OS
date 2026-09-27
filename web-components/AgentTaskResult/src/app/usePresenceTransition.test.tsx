// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePresenceTransition } from './usePresenceTransition';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Harness({ visible }: { visible: boolean }) {
  const transition = usePresenceTransition(visible);
  if (!transition.shouldRender) return null;
  return (
    <div
      data-phase={transition.phase}
      onTransitionEnd={transition.completeTransition}
    />
  );
}

describe('usePresenceTransition', () => {
  const animationFrames: FrameRequestCallback[] = [];

  beforeEach(() => {
    animationFrames.length = 0;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      animationFrames.push(callback);
      return animationFrames.length;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not render an initially hidden region', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => root.render(<Harness visible={false} />));
    expect(container.firstElementChild).toBeNull();

    act(() => root.unmount());
  });

  it('keeps an initially visible region in its entering phase until the next frame', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<Harness visible />);
    });
    expect(container.firstElementChild?.getAttribute('data-phase')).toBe('entering');

    act(() => {
      while (animationFrames.length > 0) animationFrames.shift()?.(0);
    });
    expect(container.firstElementChild?.getAttribute('data-phase')).toBe('present');

    act(() => root.unmount());
  });

  it('retains an exiting region until its own structural transition completes', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<Harness visible />);
    });
    act(() => {
      animationFrames.shift()?.(0);
    });
    act(() => {
      root.render(<Harness visible={false} />);
    });
    const region = container.firstElementChild as HTMLElement;
    expect(region.dataset.phase).toBe('exiting');

    act(() => {
      region.dispatchEvent(new TransitionEvent('transitionend', {
        bubbles: true,
        propertyName: 'opacity',
      }));
    });
    expect(container.firstElementChild).toBeNull();

    act(() => root.unmount());
  });

  it('ignores child transition events and supports an interrupted exit', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<Harness visible />);
    });
    act(() => {
      animationFrames.shift()?.(0);
    });
    act(() => {
      root.render(<Harness visible={false} />);
    });
    const region = container.firstElementChild as HTMLElement;
    const child = document.createElement('span');
    region.appendChild(child);

    act(() => {
      child.dispatchEvent(new TransitionEvent('transitionend', {
        bubbles: true,
        propertyName: 'opacity',
      }));
    });
    expect(region.dataset.phase).toBe('exiting');

    act(() => {
      root.render(<Harness visible />);
    });
    act(() => {
      while (animationFrames.length > 0) animationFrames.shift()?.(0);
    });
    expect((container.firstElementChild as HTMLElement).dataset.phase).toBe('present');

    act(() => root.unmount());
  });

  it('skips transition phases when reduced motion is requested', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<Harness visible />);
    });
    expect((container.firstElementChild as HTMLElement).dataset.phase).toBe('present');

    act(() => {
      root.render(<Harness visible={false} />);
    });
    expect(container.firstElementChild).toBeNull();

    act(() => root.unmount());
  });

  it('cancels a pending animation frame when unmounted', () => {
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => root.render(<Harness visible />));
    act(() => root.unmount());

    expect(cancelAnimationFrame).toHaveBeenCalled();
  });
});
