import { useEffect, useState } from 'react';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import PresenceRegion from '@shared/PresenceRegion';
import { cancelOperation, submitTypedInstruction } from '../bridge/assistantSessionBridge';
import type { AssistantSessionState } from '../state/assistantSessionReducer';
import { ModelPickerMenu } from './ModelPickerMenu';
import { ProgressMessage } from './ProgressMessage';

export function TypedInputState({
  state,
  showProgressElements,
  progressMessage,
}: {
  state: AssistantSessionState;
  showProgressElements: boolean;
  progressMessage: string | null;
}) {
  const [text, setText] = useState(state.typedInstruction);
  const [extractedOpen, setExtractedOpen] = useState(false);
  const canSubmit = state.canSubmitTypedInstruction;
  const trimmed = text.trim();
  const submitLabel = trimmed.length === 0 ? 'Submit (no instruction)' : 'Submit';

  useEffect(() => {
    setText(state.typedInstruction);
  }, [state.typedInstruction]);

  const submit = () => {
    if (!canSubmit) return;
    submitTypedInstruction(text);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="assistant-session-typed-input">
      <ProgressMessage show={showProgressElements} message={progressMessage} />
      <div className="assistant-session-typed-input__app-strip">
        <span className="assistant-session-typed-input__app-label">Detected Application:</span>
        <span className="assistant-session-typed-input__app-name">{state.detectedApplicationName ?? 'Unknown'}</span>
      </div>
      <div className="assistant-session-typed-input__extracted">
        <button type="button" className="assistant-session-typed-input__extracted-toggle" aria-expanded={extractedOpen} onClick={() => setExtractedOpen((prev) => !prev)}>
          <span aria-hidden="true">
            <ExecutionDisclosureChevron expanded={extractedOpen} color="var(--secondary, #4c7bf0)" />
          </span>
          <span>Extracted Text</span>
          {state.hasTextSelection && <span className="assistant-session-typed-input__selection-badge">+ Selection</span>}
          {state.ocrText ? <span className="assistant-session-typed-input__char-count">({state.ocrText.length} chars)</span> : null}
        </button>
        <PresenceRegion visible={extractedOpen} className="basil-presence" settleWithoutTransition>
          <div className="assistant-session-typed-input__extracted-body">
            {state.ocrStatus === 'running' ? (
              <div className="assistant-session-typed-input__ocr-loading">Processing image...</div>
            ) : (
              <>
                {state.hasTextSelection && state.selectedText ? (
                  <>
                    <div className="assistant-session-typed-input__selection">
                      <div className="assistant-session-typed-input__selection-title">Your Selection</div>
                      <div>{state.selectedText}</div>
                    </div>
                    <div className="assistant-session-typed-input__full-context">Full Context</div>
                  </>
                ) : null}
                <div>{state.ocrText ?? ''}</div>
              </>
            )}
          </div>
        </PresenceRegion>
      </div>
      <label className="assistant-session-typed-input__instructions">
        <span>Custom Instructions (Optional):</span>
        <textarea
          className="assistant-session-typed-input__textarea"
          placeholder="Type your request, or submit empty to let Basil decide from what's on screen."
          value={text}
          autoFocus
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
      </label>
      <div className="assistant-session-typed-input__picker-row">
        <ModelPickerMenu state={state} />
      </div>
      {state.errorMessage && <div className="assistant-session-typed-input__error">Error: {state.errorMessage}</div>}
      <div className="assistant-session-typed-input__actions">
        <button type="button" className="assistant-session-typed-input__cancel-btn" onClick={cancelOperation}>
          Cancel
        </button>
        <button type="button" className="assistant-session-typed-input__submit-btn" disabled={!canSubmit} onClick={submit}>
          {submitLabel}
          <span className="assistant-session-typed-input__shortcut">{'\u2318\u21a9'}</span>
        </button>
      </div>
    </div>
  );
}
