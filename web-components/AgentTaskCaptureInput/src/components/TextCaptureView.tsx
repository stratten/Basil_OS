import { useEffect, useRef, useState } from 'react';
import type { CaptureSnapshot } from '../types';
import RichTextComposer from '../../../shared/RichTextComposer';
import CaptureModelPickerMenu from './CaptureModelPickerMenu';
import { pickReferenceFiles, showNativeModelPicker, submitTextPrompt, updateTextDraft } from '../services/bridge';

interface Props {
  snapshot: CaptureSnapshot;
  selectedModelId: string | null;
  onModelChange: (modelId: string | null) => void;
}

export default function TextCaptureView({ snapshot, selectedModelId, onModelChange }: Props) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [draftContent, setDraftContent] = useState(snapshot.textPrompt);
  const hasHydratedInitialText = useRef(false);
  const inputDisabled = snapshot.isSubmittingTextPrompt;

  useEffect(() => {
    if (hasHydratedInitialText.current) return;
    hasHydratedInitialText.current = true;
    if (editorRef.current && snapshot.textPrompt) {
      editorRef.current.innerText = snapshot.textPrompt;
    }
    setDraftContent(snapshot.textPrompt);
    editorRef.current?.focus();
    // Hydrates once from the first snapshot's `textPrompt` (covers the
    // reload/recovery path in Package 4 row L2, where React remounts but
    // Swift's `textPrompt` already holds an in-progress draft); every
    // subsequent keystroke is owned by this component's own local state
    // plus the `updateTextDraft` intent, not re-synced from later
    // snapshots, so the user's own typing is never overwritten mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleDraftChange(value: string): void {
    setDraftContent(value);
    updateTextDraft(value);
  }

  function handleSubmit(): void {
    const content = editorRef.current?.innerText.trim() ?? '';
    if (!content || inputDisabled) return;
    submitTextPrompt(content, selectedModelId ?? undefined);
  }

  return (
    <div className="text-capture-body">
      <span className="text-capture-body__label">Enter your request:</span>
      <RichTextComposer
        editorRef={editorRef}
        editorClassName="text-capture-editor"
        disabled={inputDisabled}
        placeholder="Enter your request..."
        submitDisabled={inputDisabled || !draftContent.trim()}
        onDraftChange={handleDraftChange}
        onSubmit={handleSubmit}
        toolbarEnd={(
          <button
            type="button"
            className="text-capture-attach-btn"
            onClick={() => pickReferenceFiles()}
            disabled={inputDisabled}
            title="Attach files or folders"
            aria-label="Attach files or folders"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
            </svg>
          </button>
        )}
        bottomStart={(
          <CaptureModelPickerMenu
            disabled={inputDisabled}
            selectedModelId={selectedModelId}
            onModelChange={onModelChange}
            variant="default"
            onRequestNativeMenu={(models, currentModelId, anchorRect) => {
              showNativeModelPicker(
                models.map((model) => ({
                  id: model.id,
                  displayName: model.display_name,
                  category: model.category,
                })),
                currentModelId,
                {
                  x: anchorRect.x,
                  y: anchorRect.y,
                  width: anchorRect.width,
                  height: anchorRect.height,
                },
              );
            }}
          />
        )}
      />
    </div>
  );
}
