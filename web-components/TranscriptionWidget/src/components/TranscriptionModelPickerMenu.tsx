// web-components/TranscriptionWidget/src/components/TranscriptionModelPickerMenu.tsx

import { selectTranscriptionModel, showTranscriptionModelMenu } from '../bridge/transcriptionWidgetBridge';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import type { SharedReasoningModel } from '../../../shared/ReasoningModelPicker';
import type { TranscriptionState } from '../state/transcriptionReducer';
import { TranscriptionSymbol } from './TranscriptionSymbol';

export function TranscriptionModelPickerMenu({
  state,
  style,
}: {
  state: TranscriptionState;
  style: 'miniChevron' | 'fullLabel';
}) {
  const models: SharedReasoningModel[] = state.availableTranscriptionModels.map((model) => ({
    id: model.id,
    name: model.displayName,
    display_name: model.displayName,
    category: model.isApiModel ? 'api' : 'local',
  }));
  // fullLabel locks during recording (matches TranscriptionWidget.swift:499);
  // miniChevron stays interactable mid-record (matches the comment at
  // TranscriptionWidget.swift:208-216 explaining why the mini picker does not
  // lock on isRecording).
  const disabled = style === 'fullLabel' ? state.isRecording || state.isSwappingTranscriptionModel : state.isSwappingTranscriptionModel;
  if (style === 'miniChevron') {
    return (
      <button
        type="button"
        className="rich-text-model-picker-trigger rich-text-model-picker-trigger--mini-chevron"
        aria-label="Transcription model"
        aria-haspopup="menu"
        disabled={disabled || models.length === 0}
        onClick={(event) => {
          const { x, y, width, height } = event.currentTarget.getBoundingClientRect();
          showTranscriptionModelMenu(state.availableTranscriptionModels, state.currentTranscriptionModelId, { x, y, width, height });
        }}
      >
        {state.isSwappingTranscriptionModel ? (
          <span className="rich-text-model-picker-trigger__spinner" aria-hidden="true" />
        ) : (
          <TranscriptionSymbol name="chevronDown" size={9} />
        )}
      </button>
    );
  }
  return (
    <ReasoningModelPicker
      models={models}
      selectedModelId={state.currentTranscriptionModelId || undefined}
      disabled={disabled}
      busy={state.isSwappingTranscriptionModel}
      ariaLabel="Transcription model"
      variant="default"
      onRequestNativeMenu={({ x, y, width, height }) => {
        showTranscriptionModelMenu(
          state.availableTranscriptionModels,
          state.currentTranscriptionModelId,
          { x, y, width, height },
        );
      }}
      onModelChange={(modelId) => {
        if (modelId) selectTranscriptionModel(modelId);
      }}
      placeholder={models.length === 0 ? 'No transcription models available' : 'Select model'}
    />
  );
}
