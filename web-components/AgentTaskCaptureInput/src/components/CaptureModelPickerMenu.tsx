import { useEffect, useState } from 'react';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import type { SharedReasoningModel } from '../../../shared/ReasoningModelPicker';
import { getReasoningModels, isApiReady, type ReasoningModel } from '../services/api';

interface Props {
  disabled: boolean;
  selectedModelId: string | null;
  onModelChange: (modelId: string | null) => void;
  variant?: 'default' | 'miniChevron';
  onRequestNativeMenu?: (models: ReasoningModel[], selectedModelId: string | null, anchorRect: DOMRect) => void;
}

export default function CaptureModelPickerMenu({
  disabled,
  selectedModelId,
  onModelChange,
  variant = 'default',
  onRequestNativeMenu,
}: Props) {
  const [models, setModels] = useState<ReasoningModel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!isApiReady()) return;
    let cancelled = false;
    getReasoningModels()
      .then((data) => {
        if (cancelled) return;
        setModels(data.models);
        if (selectedModelId === null) onModelChange(data.current_model);
      })
      .catch((error) => {
        console.error('[CaptureModelPickerMenu] Failed to load models:', error);
        setLoadError('Models unavailable');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Runs once per mount, mirroring `TextFollowUp.tsx`'s own one-shot model
    // fetch — the capture widget's model choice does not need to react to
    // this list changing again after the widget is already open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sharedModels: SharedReasoningModel[] = models.map((model) => ({
    id: model.id,
    name: model.display_name,
    display_name: model.display_name,
    category: model.category,
  }));

  return (
    <div className="capture-model-picker">
      <ReasoningModelPicker
        models={sharedModels}
        selectedModelId={selectedModelId ?? undefined}
        disabled={disabled}
        variant={variant}
        busy={isLoading}
        onModelChange={(modelId) => onModelChange(modelId ?? null)}
        onRequestNativeMenu={onRequestNativeMenu
          ? (anchorRect) => onRequestNativeMenu(models, selectedModelId, anchorRect)
          : undefined}
        ariaLabel={loadError ?? 'Reasoning model'}
        placeholder={isLoading ? 'Loading models…' : 'Choose model'}
      />
      {loadError ? <span className="capture-model-picker__error" role="status">{loadError}</span> : null}
    </div>
  );
}
