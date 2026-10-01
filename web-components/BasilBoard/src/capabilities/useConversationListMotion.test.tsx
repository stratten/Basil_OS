import { render } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationListItem } from '../contracts';
import { useConversationListMotion } from './useConversationListMotion';

const ROW_HEIGHT = 40;

function item(id: string): ConversationListItem {
  return { id, created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z', message_count: 1 };
}

function Harness({ ids }: { ids: string[] }) {
  const listRef = useRef<HTMLUListElement>(null);
  useConversationListMotion(listRef, ids.map(item));
  return (
    <ul ref={listRef}>
      {ids.map((id) => <li key={id} data-conversation-id={id}>{id}</li>)}
    </ul>
  );
}

describe('useConversationListMotion', () => {
  const animate = vi.fn();
  const originalAnimate = HTMLElement.prototype.animate;
  const originalOffsetTop = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetTop');

  beforeEach(() => {
    animate.mockReset();
    HTMLElement.prototype.animate = animate as unknown as typeof HTMLElement.prototype.animate;
    Object.defineProperty(HTMLElement.prototype, 'offsetTop', {
      configurable: true,
      get(this: HTMLElement) {
        const parent = this.parentElement;
        return parent ? Array.from(parent.children).indexOf(this) * ROW_HEIGHT : 0;
      },
    });
  });

  afterEach(() => {
    HTMLElement.prototype.animate = originalAnimate;
    if (originalOffsetTop) Object.defineProperty(HTMLElement.prototype, 'offsetTop', originalOffsetTop);
  });

  it('does not animate the first render', () => {
    render(<Harness ids={['a', 'b']} />);
    expect(animate).not.toHaveBeenCalled();
  });

  it('slides moved rows from their previous position', () => {
    const { rerender } = render(<Harness ids={['a', 'b']} />);
    rerender(<Harness ids={['b', 'a']} />);
    const transforms = animate.mock.calls.map(([keyframes]) => keyframes[0].transform);
    expect(transforms).toContain(`translateY(${-ROW_HEIGHT}px)`);
    expect(transforms).toContain(`translateY(${ROW_HEIGHT}px)`);
    expect(animate.mock.calls[0][1]).toMatchObject({ duration: 320, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
  });

  it('fades in a new row and slides the rows below it', () => {
    const { rerender } = render(<Harness ids={['a', 'b']} />);
    rerender(<Harness ids={['c', 'a', 'b']} />);
    const enter = animate.mock.calls.find(([keyframes]) => keyframes[0].opacity === 0);
    expect(enter?.[1]).toMatchObject({ duration: 240 });
    expect(animate).toHaveBeenCalledTimes(3);
  });

  it('does not animate when only content changes without a reorder', () => {
    const { rerender } = render(<Harness ids={['a', 'b']} />);
    rerender(<Harness ids={['a', 'b']} />);
    expect(animate).not.toHaveBeenCalled();
  });

  it('respects reduced motion', () => {
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: vi.fn(() => ({ matches: true })) });
    try {
      const { rerender } = render(<Harness ids={['a', 'b']} />);
      rerender(<Harness ids={['b', 'a']} />);
      expect(animate).not.toHaveBeenCalled();
    } finally {
      delete (window as { matchMedia?: unknown }).matchMedia;
    }
  });
});
