import { useState } from 'react';
import { cancelTypedRefinement, stopRefinementRecording, submitTypedRefinement } from '../../bridge/assistantSessionBridge';
import type { AssistantSessionState } from '../../state/assistantSessionReducer';

export function RefinementPanel({
  state,
  isTypedRefinementMode,
  onCloseTypedRefinement,
}: {
  state: AssistantSessionState;
  isTypedRefinementMode: boolean;
  onCloseTypedRefinement: () => void;
}) {
  const [typedRefinement, setTypedRefinement] = useState('');
  const trimmed = typedRefinement.trim();

  return (
    <>
      {state.isRefinementMode && state.isRecording && (
        <div className="assistant-session-refinement assistant-session-refinement--recording basil-presence-enter">
          <button type="button" className="assistant-session-actions__btn assistant-session-actions__btn--recording" title="Stop refinement recording and process" onClick={stopRefinementRecording}>
            Stop Recording
          </button>
        </div>
      )}
      {isTypedRefinementMode && state.assistantSessionStatus !== 'running' && (
        <div className="assistant-session-refinement__typed basil-presence-enter">
          <div className="assistant-session-refinement__typed-label">Refinement instruction:</div>
          <textarea
            className="assistant-session-refinement__textarea"
            value={typedRefinement}
            autoFocus
            onChange={(event) => setTypedRefinement(event.target.value)}
          />
          <div className="assistant-session-refinement__typed-actions">
            <button
              type="button"
              className="assistant-session-actions__btn assistant-session-actions__btn--muted"
              title="Cancel typed refinement"
              onClick={() => {
                setTypedRefinement('');
                onCloseTypedRefinement();
                cancelTypedRefinement();
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="assistant-session-actions__btn assistant-session-actions__btn--success"
              disabled={trimmed.length === 0}
              title={trimmed.length === 0 ? 'Type an instruction to enable submit' : 'Submit typed refinement'}
              onClick={() => {
                submitTypedRefinement(trimmed);
                setTypedRefinement('');
                onCloseTypedRefinement();
              }}
            >
              Submit
            </button>
          </div>
        </div>
      )}
      {state.isRefinementMode && (
        <div className="assistant-session-refinement__indicator basil-presence-enter">
          <span>Refinement Mode</span>
          {state.iterationCount > 0 && <span className="assistant-session-refinement__iteration">(Iteration {state.iterationCount})</span>}
        </div>
      )}
      {state.isRefinementMode && state.transcriptionStatus === 'idle' && !state.isRecording && (
        <div className="assistant-session-refinement__hint basil-presence-enter">
          Press {state.hotkeyDisplayString ?? 'the assistant hotkey'} or click Refine to continue
        </div>
      )}
    </>
  );
}
