import { selectModel, showNativeModelPicker } from '../bridge/assistantSessionBridge';
import type { AssistantSessionState } from '../state/assistantSessionReducer';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import type { SharedReasoningModel } from '../../../shared/ReasoningModelPicker';

export function ModelPickerMenu({
  state,
  variant = 'default',
}: {
  state: AssistantSessionState;
  variant?: 'default' | 'miniChevron';
}) {
  const nativeModels = [
    ...state.localModels,
    ...(state.useApiModels ? state.apiModels : []),
  ];
  const models: SharedReasoningModel[] = nativeModels.map((model) => (
    {
      id: model.id,
      name: model.displayName,
      display_name: model.displayName,
      category: model.isApiModel ? 'api' as const : 'local' as const,
    }
  ));
  // The reasoning model is read only when the request is sent (status flips to running), so it stays selectable throughout audio capture.
  const disabled = state.assistantSessionStatus === 'running' || state.isLoadingModels;

  if (variant === 'miniChevron') {
    return (
      <button
        type="button"
        className="rich-text-model-picker-trigger rich-text-model-picker-trigger--mini-chevron"
        aria-label="Reasoning model"
        aria-haspopup="menu"
        disabled={disabled || nativeModels.length === 0}
        onClick={(event) => {
          const { x, y, width, height } = event.currentTarget.getBoundingClientRect();
          showNativeModelPicker(nativeModels, state.selectedModelId, { x, y, width, height });
        }}
      >
        <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" />
        </svg>
      </button>
    );
  }

  return (
    <ReasoningModelPicker
      models={models}
      selectedModelId={state.selectedModelId ?? undefined}
      disabled={disabled}
      variant={variant}
      onModelChange={(modelId) => {
        if (modelId) selectModel(modelId);
      }}
      placeholder={state.isLoadingModels ? 'Loading models…' : 'Choose model'}
    />
  );
}
