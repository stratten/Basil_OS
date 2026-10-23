import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationMessageItem } from '../contracts';
import ConversationMessageRow from './ConversationMessageRow';

vi.mock('../services/bridge', () => ({ openExistingAgentTaskWidget: vi.fn() }));

let frameCallbacks: FrameRequestCallback[] = [];

function runFrame(timestamp: number) {
  const callbacks = frameCallbacks;
  frameCallbacks = [];
  act(() => {
    for (const callback of callbacks) callback(timestamp);
  });
}

function assistantMessage(id: string, content: string, metadata: Record<string, unknown> = {}): ConversationMessageItem {
  return { id, role: 'assistant', content, timestamp: '2026-09-30T12:27:00Z', metadata };
}

function renderRow(message: ConversationMessageItem) {
  return render(
    <ConversationMessageRow
      message={message}
      modelDisplayNames={new Map()}
      onCopy={vi.fn()}
      onPreviewArtifact={vi.fn()}
      onViewAllArtifacts={vi.fn()}
    />,
  );
}

function bubbleText(container: HTMLElement): string {
  return (container.querySelector('.chats-message-bubble')?.textContent ?? '').trim();
}

describe('ConversationMessageRow streaming', () => {
  beforeEach(() => {
    frameCallbacks = [];
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameCallbacks.push(callback);
      return frameCallbacks.length;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reveals a streaming reply on word boundaries and keeps the bubble width stable', () => {
    const content = 'One two three four five six seven eight';
    const { container, rerender } = renderRow(assistantMessage('stream-row-1', content, { streaming: true }));

    expect(container.querySelector('.chats-message')?.classList.contains('is-stream-stable')).toBe(true);
    expect(bubbleText(container)).toBe('');

    runFrame(0);
    expect(bubbleText(container)).toBe('One');

    rerender(
      <ConversationMessageRow
        message={assistantMessage('stream-row-1', content, { streaming: false })}
        modelDisplayNames={new Map()}
        onCopy={vi.fn()}
        onPreviewArtifact={vi.fn()}
        onViewAllArtifacts={vi.fn()}
      />,
    );
    for (let frame = 1; frame <= 30 && frameCallbacks.length > 0; frame += 1) runFrame(frame * 100);

    expect(bubbleText(container)).toBe(content);
    expect(container.querySelector('.chats-message')?.classList.contains('is-stream-stable')).toBe(true);
  });

  it('renders a reply that was complete at mount immediately and without the stable-width class', () => {
    const { container } = renderRow(assistantMessage('history-row-1', 'Complete history reply'));

    expect(bubbleText(container)).toBe('Complete history reply');
    expect(container.querySelector('.chats-message')?.classList.contains('is-stream-stable')).toBe(false);
    expect(frameCallbacks).toHaveLength(0);
  });
});

describe('ConversationMessageRow Thinking toggle', () => {
  it('uses the shared stroked chevron rather than a filled triangle', () => {
    renderRow(assistantMessage('thinking-row-1', 'Answer', { thinking: 'Reasoning steps' }));

    const toggle = screen.getByRole('button', { name: /View thinking/ });
    const svg = toggle.querySelector('.chats-thinking-chevron svg') as SVGElement | null;
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('fill')).toBe('none');
    expect(svg?.getAttribute('stroke')).toBe('var(--secondary, #33559b)');
    expect(svg?.querySelector('path')?.getAttribute('d')).toBe('M4 6l4 4 4-4');
    expect(svg?.style.transform).toBe('rotate(-90deg)');
    expect(toggle.textContent ?? '').not.toMatch(/[\u25B6\u25B8\u25BA\u25BC\u25BE]/);

    fireEvent.click(toggle);

    const expandedSvg = toggle.querySelector('.chats-thinking-chevron svg') as SVGElement | null;
    expect(expandedSvg?.style.transform).toBe('rotate(0deg)');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Reasoning steps')).toBeTruthy();
  });
});
