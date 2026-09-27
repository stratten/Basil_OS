import { NativeSymbol } from '../NativeSymbol';

export function HistoryActionButtons({
  isEditMode,
  sampleSaved,
  savingSample,
  onEnterEdit,
  onCancelEdit,
  onApplyEdits,
  onSaveAsSample,
  onRefine,
}: {
  isEditMode: boolean;
  sampleSaved: boolean;
  savingSample: boolean;
  onEnterEdit: () => void;
  onCancelEdit: () => void;
  onApplyEdits: () => void;
  onSaveAsSample: () => void;
  onRefine: () => void;
}) {
  return (
    <div className="assistant-output-history-detail__actions">
      {isEditMode ? (
        <>
          <button type="button" className="assistant-output-history-detail__action assistant-output-history-detail__action--muted" onClick={onCancelEdit}>
            <NativeSymbol name="cancel" size={14} /> Cancel
          </button>
          <button type="button" className="assistant-output-history-detail__action assistant-output-history-detail__action--success" onClick={onApplyEdits}>
            <NativeSymbol name="check" size={14} /> Apply Edits
          </button>
        </>
      ) : (
        <button type="button" className="assistant-output-history-detail__action assistant-output-history-detail__action--primary" onClick={onEnterEdit}>
          <NativeSymbol name="edit" size={14} /> Edit
        </button>
      )}
      <button
        type="button"
        className={`assistant-output-history-detail__action${sampleSaved ? ' assistant-output-history-detail__action--success' : ' assistant-output-history-detail__action--primary'}`}
        disabled={sampleSaved || savingSample}
        onClick={onSaveAsSample}
      >
        {!savingSample && <NativeSymbol name={sampleSaved ? 'check' : 'save'} size={14} />}
        {sampleSaved ? 'Saved' : savingSample ? 'Saving…' : 'Save as Sample'}
      </button>
      {!isEditMode && (
        <button type="button" className="assistant-output-history-detail__action assistant-output-history-detail__action--primary" onClick={onRefine}>
          <NativeSymbol name="refine" size={14} /> Refine
        </button>
      )}
    </div>
  );
}
