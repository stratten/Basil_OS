import { useState } from 'react';
import { copyMarkdown, copyRichText } from '../../bridge/assistantSessionBridge';
import type { AssistantSessionPasteOutcome } from '../../bridge/types';
import { MarkdownView } from '../MarkdownView';
import { NativeSymbol } from '../NativeSymbol';
import { useCopyFeedback } from '@shared/useCopyFeedback';
import { PasteStatusLine } from './PasteStatusLine';

export function OutputCard({
  output,
  isEditMode,
  editedContent,
  onEditedContentChange,
  fallbackModelUsed,
  pasteOutcome = null,
  pasteTargetApplicationName = null,
}: {
  output: string;
  isEditMode: boolean;
  editedContent: string;
  onEditedContentChange: (value: string) => void;
  fallbackModelUsed?: string | null;
  pasteOutcome?: AssistantSessionPasteOutcome | null;
  pasteTargetApplicationName?: string | null;
}) {
  const [hovering, setHovering] = useState(false);
  const { copiedKey: copiedKind, flash } = useCopyFeedback<'richText' | 'markdown'>();

  return (
    <div className="assistant-session-result__output-wrap">
      <div className="assistant-session-result__output-label">
        Output:
        {fallbackModelUsed && (
          <span
            className="assistant-session-result__fallback-badge"
            title={`Preferred model was unreachable before any response; answered by local fallback: ${fallbackModelUsed}`}
          >
            Answered with local fallback
          </span>
        )}
        <PasteStatusLine outcome={pasteOutcome} applicationName={pasteTargetApplicationName} />
      </div>
      <div
        className="assistant-session-result__output-card"
        onMouseEnter={() => setHovering(true)}
        onMouseLeave={() => setHovering(false)}
      >
        {isEditMode ? (
          <textarea
            className="assistant-session-result__edit-textarea"
            value={editedContent}
            onChange={(event) => onEditedContentChange(event.target.value)}
            autoFocus
          />
        ) : (
          <div className="assistant-session-result__output">
            <MarkdownView content={output} />
          </div>
        )}
        {!isEditMode && (
          <div className={`assistant-session-result__copy-group${hovering || copiedKind ? ' assistant-session-result__copy-group--visible' : ''}`}>
            <button
              type="button"
              title="Copy rich text"
              className="assistant-session-result__copy-btn"
              onClick={() => {
                copyRichText();
                flash('richText');
              }}
            >
              <NativeSymbol name={copiedKind === 'richText' ? 'copied' : 'copyRich'} size={12} />
            </button>
            <button
              type="button"
              title="Copy markdown"
              className="assistant-session-result__copy-btn"
              onClick={() => {
                copyMarkdown();
                flash('markdown');
              }}
            >
              <NativeSymbol name={copiedKind === 'markdown' ? 'copied' : 'copyMarkdown'} size={12} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
