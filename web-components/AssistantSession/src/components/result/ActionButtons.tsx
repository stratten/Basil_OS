import { cancelEditMode, enterEditMode, enterVoiceRefinement, saveAsSample } from '../../bridge/assistantSessionBridge';
import type { AssistantSessionState } from '../../state/assistantSessionReducer';
import { NativeSymbol } from '../NativeSymbol';
import { RefineBadge } from '../RefineBadge';

export function ActionButtons({
  state,
  sampleContent,
  isTypedRefinementMode,
  onEnterTypedRefinement,
  onApplyEdits,
}: {
  state: AssistantSessionState;
  sampleContent: string;
  isTypedRefinementMode: boolean;
  onEnterTypedRefinement: () => void;
  onApplyEdits: () => void;
}) {
  const actionsVisible =
    state.assistantSessionStatus === 'completed' &&
    state.shouldPersistUI &&
    !state.isRecording &&
    !isTypedRefinementMode;

  if (!actionsVisible) return null;

  const handleSaveAsSample = () => {
    saveAsSample(sampleContent);
  };

  return (
    <div className="assistant-session-actions">
      {state.isEditMode ? (
        <>
          <button type="button" className="assistant-session-actions__btn assistant-session-actions__btn--muted" title="Cancel editing and revert changes" onClick={cancelEditMode}>
            <NativeSymbol name="cancel" size={14} /> Cancel
          </button>
          <button type="button" className="assistant-session-actions__btn assistant-session-actions__btn--success" title="Apply your edits to this output" onClick={onApplyEdits}>
            <NativeSymbol name="check" size={14} /> Apply Edits
          </button>
        </>
      ) : (
        <>
          <button type="button" className="assistant-session-actions__btn assistant-session-actions__btn--primary" title="Edit this output before saving" onClick={enterEditMode}>
            <NativeSymbol name="edit" size={14} /> Edit
          </button>
        </>
      )}
      <button
        type="button"
        className={`assistant-session-actions__btn${state.sampleSaved ? ' assistant-session-actions__btn--success' : ' assistant-session-actions__btn--primary'}`}
        disabled={state.sampleSaved || state.savingSample}
        title={state.isEditMode ? 'Save this edited version as a writing sample' : 'Save this output as a writing sample to improve personalization'}
        onClick={handleSaveAsSample}
      >
        {!state.savingSample && (
          <NativeSymbol name={state.sampleSaved ? 'check' : 'save'} size={14} />
        )}
        {state.sampleSaved ? 'Saved' : state.savingSample ? 'Saving…' : 'Save as Sample'}
      </button>
      {!state.isEditMode && (
        <>
          <button type="button" className="assistant-session-actions__icon-btn" title="Speak additional instructions to refine this output" onClick={enterVoiceRefinement}>
            <RefineBadge kind="mic" />
          </button>
          <button type="button" className="assistant-session-actions__icon-btn" title="Type additional instructions to refine this output" onClick={onEnterTypedRefinement}>
            <RefineBadge kind="pencil" />
          </button>
        </>
      )}
    </div>
  );
}
