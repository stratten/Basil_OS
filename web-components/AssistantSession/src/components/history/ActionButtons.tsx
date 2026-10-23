import { NativeSymbol } from '../NativeSymbol';
import { RefineBadge } from '../RefineBadge';
import type { HistoryRefinementInput } from '../../bridge/historyTypes';
import type { SampleContextType } from '../../services/historyApi';

export type HistorySampleStatus = 'unsaved' | 'saved' | 'changed';

export function HistoryActionButtons({
  isEditMode,
  sampleStatus,
  savingSample,
  contextPicker,
  onEnterEdit,
  onCancelEdit,
  onApplyEdits,
  onSaveAsSample,
  onRefine,
}: {
  isEditMode: boolean;
  sampleStatus: HistorySampleStatus;
  savingSample: boolean;
  contextPicker: {
    value: SampleContextType;
    options: ReadonlyArray<{ value: SampleContextType; label: string }>;
    onChange: (value: SampleContextType) => void;
  } | null;
  onEnterEdit: () => void;
  onCancelEdit: () => void;
  onApplyEdits: () => void;
  onSaveAsSample: () => void;
  onRefine: (input: HistoryRefinementInput) => void;
}) {
  const sampleButtonLabel = savingSample
    ? 'Saving…'
    : sampleStatus === 'changed' ? 'Update Sample' : 'Save as Sample';
  const contextLabel = contextPicker?.options.find((option) => option.value === contextPicker.value)?.label;

  return (
    <div className="assistant-output-history-detail__actions">
      {contextPicker && sampleStatus === 'unsaved' && (isEditMode ? (
        <select
          className="assistant-output-history-detail__context-select"
          aria-label="Sample context"
          value={contextPicker.value}
          disabled={savingSample}
          onChange={(event) => contextPicker.onChange(event.target.value as SampleContextType)}
        >
          {contextPicker.options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      ) : (
        <span className="assistant-output-history-detail__context-chip" title="Writing sample context. Edit to change it.">
          {contextLabel}
        </span>
      ))}
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
      {sampleStatus !== 'saved' && (
        <button
          type="button"
          className="assistant-output-history-detail__action assistant-output-history-detail__action--primary"
          disabled={savingSample}
          onClick={onSaveAsSample}
        >
          {!savingSample && <NativeSymbol name="save" size={14} />}
          {sampleButtonLabel}
        </button>
      )}
      {!isEditMode && (
        <>
          <button
            type="button"
            className="assistant-output-history-detail__action assistant-output-history-detail__action--primary assistant-output-history-detail__action--icon"
            title="Speak additional instructions to refine this output"
            aria-label="Refine by voice"
            onClick={() => onRefine('voice')}
          >
            <RefineBadge kind="mic" />
          </button>
          <button
            type="button"
            className="assistant-output-history-detail__action assistant-output-history-detail__action--primary assistant-output-history-detail__action--icon"
            title="Type additional instructions to refine this output"
            aria-label="Refine by typing"
            onClick={() => onRefine('typed')}
          >
            <RefineBadge kind="pencil" />
          </button>
        </>
      )}
      {sampleStatus !== 'unsaved' && (
        <span
          className="assistant-output-history-detail__saved-indicator"
          title={sampleStatus === 'changed'
            ? 'This output is saved as a writing sample; the text shown differs from the saved version.'
            : 'This output is saved as a writing sample.'}
        >
          <NativeSymbol name="check" size={12} /> Saved as sample
        </span>
      )}
    </div>
  );
}
