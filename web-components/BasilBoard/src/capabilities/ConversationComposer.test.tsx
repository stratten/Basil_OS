import { createRef } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ConversationComposer from './ConversationComposer';

function renderComposer(
  onSubmit = vi.fn(),
  options: Partial<{ processing: boolean; canceling: boolean }> = {},
) {
  render(
    <ConversationComposer
      editorRef={createRef<HTMLDivElement>()}
      attachmentPaths={[]}
      processing={options.processing ?? false}
      canceling={options.canceling ?? false}
      voiceState="idle"
      activeFormats={{}}
      models={[]}
      delegationOptOut={false}
      onDelegationOptOutChange={vi.fn()}
      sendDisabled={false}
      canRetryUnsent={false}
      canRestoreFailed={false}
      onRetryUnsent={vi.fn()}
      onRestoreFailed={vi.fn()}
      onRemoveAttachment={vi.fn()}
      onExecuteCommand={vi.fn()}
      onToggleInlineCode={vi.fn()}
      onDraftChange={vi.fn()}
      onHtmlChange={vi.fn()}
      onSubmit={onSubmit}
      onAttach={vi.fn()}
      onModelChange={vi.fn()}
      onStartVoice={vi.fn()}
      onStopVoice={vi.fn()}
      onCancelVoice={vi.fn()}
      onCancelResponse={vi.fn()}
      onPasteImages={vi.fn()}
      onArmFileDropTarget={vi.fn()}
      onClearFileDropTarget={vi.fn()}
    />,
  );
}

describe('ConversationComposer', () => {
  it('renders an icon-only accessible send control', async () => {
    const onSubmit = vi.fn();
    renderComposer(onSubmit);

    const sendButton = screen.getByRole('button', { name: 'Send' });
    expect(sendButton.textContent).toBe('');
    expect(sendButton.querySelector('svg')).toBeTruthy();
    const sendShortcut = document.querySelector('.chats-send-shortcut');
    expect(sendShortcut?.textContent).toBe('⌘↩');

    await userEvent.click(sendButton);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('explains Conversation only and consumes the shared Stop action', () => {
    renderComposer(vi.fn(), { processing: true });

    expect(screen.getByRole('checkbox', { name: 'Conversation only' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'About Conversation only' }).getAttribute('title')).toContain('Agent Task tools');
    expect(screen.getByRole('button', { name: 'Stop' }).className).toContain('basil-stop-action');
  });
});
