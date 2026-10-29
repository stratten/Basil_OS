import { createRef, useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ReasoningModel } from '../services/api';
import ConversationComposer from './ConversationComposer';

const richTextComposerMock = vi.hoisted(() => vi.fn(() => null));
vi.mock('../../../shared/RichTextComposer', () => ({ default: richTextComposerMock }));

const stableEditorRef = createRef<HTMLDivElement>();
const stableAttachmentPaths: string[] = [];
const stableActiveFormats: Record<string, boolean> = {};
const stableModels: ReasoningModel[] = [];
const stableHandlers = {
  onDelegationOptOutChange: vi.fn(),
  onRetryUnsent: vi.fn(),
  onRestoreFailed: vi.fn(),
  onRemoveAttachment: vi.fn(),
  onExecuteCommand: vi.fn(),
  onToggleInlineCode: vi.fn(),
  onDraftChange: vi.fn(),
  onHtmlChange: vi.fn(),
  onSubmit: vi.fn(),
  onAttach: vi.fn(),
  onModelChange: vi.fn(),
  onStartVoice: vi.fn(),
  onStopVoice: vi.fn(),
  onCancelVoice: vi.fn(),
  onCancelResponse: vi.fn(),
  onPasteImages: vi.fn(),
  onArmFileDropTarget: vi.fn(),
  onClearFileDropTarget: vi.fn(),
};

function Harness() {
  const [tick, setTick] = useState(0);
  return (
    <div>
      <button type="button" onClick={() => setTick((value) => value + 1)}>{`tick ${tick}`}</button>
      <ConversationComposer
        editorRef={stableEditorRef}
        attachmentPaths={stableAttachmentPaths}
        processing={false}
        canceling={false}
        voiceState="idle"
        activeFormats={stableActiveFormats}
        models={stableModels}
        delegationOptOut={false}
        sendDisabled={false}
        canRetryUnsent={false}
        canRestoreFailed={false}
        {...stableHandlers}
      />
    </div>
  );
}

describe('ConversationComposer memoization', () => {
  it('does not re-render when a parent re-renders with referentially stable props', async () => {
    richTextComposerMock.mockClear();
    render(<Harness />);
    expect(richTextComposerMock).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'tick 0' }));

    expect(screen.getByRole('button', { name: 'tick 1' })).toBeTruthy();
    expect(richTextComposerMock).toHaveBeenCalledTimes(1);
  });
});
