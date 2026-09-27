import { memo, useState, type ReactElement } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ConversationMessageItem } from '../contracts';
import ConversationTranscript from './ConversationTranscript';

const renderCounts = vi.hoisted(() => new Map<string, number>());

vi.mock('./ConversationMessageRow', () => ({
  default: memo((props: { message: ConversationMessageItem }): ReactElement => {
    renderCounts.set(props.message.id, (renderCounts.get(props.message.id) ?? 0) + 1);
    return <div data-testid={`row-${props.message.id}`}>{props.message.content}</div>;
  }),
}));

const stableModelDisplayNames = new Map<string, string>();
const stableOnCopy = vi.fn().mockResolvedValue(undefined);
const stableOnRetryLoad = vi.fn();
const stableOnPinnedChange = vi.fn();
const stableOnPreviewArtifact = vi.fn();
const stableOnViewAllArtifacts = vi.fn();

function messagesFixture(): ConversationMessageItem[] {
  return [
    { id: 'assistant-1', role: 'assistant', content: 'First reply', timestamp: '2026-08-01T00:00:00Z', metadata: {} },
    { id: 'assistant-2', role: 'assistant', content: 'Second reply', timestamp: '2026-08-01T00:01:00Z', metadata: {} },
    { id: 'assistant-3', role: 'assistant', content: 'Third reply', timestamp: '2026-08-01T00:02:00Z', metadata: {} },
  ];
}

function Harness() {
  const [messages, setMessages] = useState(messagesFixture());
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          setMessages((current) => current.map((message) => (
            message.id === 'assistant-2' ? { ...message, content: 'Second reply, updated' } : message
          )));
        }}
      >
        stream-into-second
      </button>
      <ConversationTranscript
        viewportRef={{ current: null }}
        messages={messages}
        loading={false}
        modelDisplayNames={stableModelDisplayNames}
        onRetryLoad={stableOnRetryLoad}
        onPinnedChange={stableOnPinnedChange}
        onCopy={stableOnCopy}
        onPreviewArtifact={stableOnPreviewArtifact}
        onViewAllArtifacts={stableOnViewAllArtifacts}
      />
    </div>
  );
}

describe('ConversationTranscript row-level render isolation', () => {
  it('only re-renders the message row whose content actually changed', async () => {
    renderCounts.clear();
    render(<Harness />);
    expect(renderCounts.get('assistant-1')).toBe(1);
    expect(renderCounts.get('assistant-2')).toBe(1);
    expect(renderCounts.get('assistant-3')).toBe(1);

    await userEvent.click(screen.getByRole('button', { name: 'stream-into-second' }));

    expect(screen.getByTestId('row-assistant-2').textContent).toBe('Second reply, updated');
    expect(renderCounts.get('assistant-1')).toBe(1);
    expect(renderCounts.get('assistant-2')).toBe(2);
    expect(renderCounts.get('assistant-3')).toBe(1);
  });
});
