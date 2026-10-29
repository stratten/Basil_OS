import ReasoningModelPicker from '../../../../shared/ReasoningModelPicker';
import type { ReasoningModel } from '../../services/api';

export const DEFAULT_MODEL_LABEL = 'Default model';

interface Props {
  models: ReasoningModel[];
  // The pinned model id; an empty string means "use the default model".
  modelId: string;
  onChange: (modelId: string) => void;
  disabled?: boolean;
}

// The pinned model may no longer be installed or enabled. Keep it visible
// (marked unavailable) rather than silently showing "Default model", so the
// user can see what the schedule is pinned to before deciding to change it.
export function modelsWithPinned(models: ReasoningModel[], modelId: string): ReasoningModel[] {
  if (!modelId || models.some(model => model.id === modelId)) return models;
  return [
    ...models,
    {
      id: modelId,
      name: modelId,
      display_name: `${modelId} (unavailable)`,
      provider: '',
      category: 'custom',
      is_api_model: false,
    },
  ];
}

// Human-readable name for a pinned model id, for the read view.
export function describeScheduledModel(models: ReasoningModel[], modelId?: string | null): string {
  if (!modelId) return DEFAULT_MODEL_LABEL;
  const match = models.find(model => model.id === modelId);
  return match ? match.display_name || match.name : modelId;
}

// Optional per-schedule reasoning model. "Default model" (the empty value)
// follows whichever reasoning model the app is set to use at run time.
export default function ScheduledModelField({ models, modelId, onChange, disabled }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontFamily: 'var(--font-family-light)',
        fontSize: 'var(--font-size-callout)',
        color: 'var(--text-secondary)',
      }}
    >
      <span style={{ fontFamily: 'var(--font-family-medium)', color: 'var(--text-tertiary)', minWidth: 72 }}>
        Model
      </span>
      <ReasoningModelPicker
        models={modelsWithPinned(models, modelId)}
        selectedModelId={modelId || undefined}
        disabled={Boolean(disabled)}
        clearOptionLabel={DEFAULT_MODEL_LABEL}
        ariaLabel="Scheduled task model"
        onModelChange={next => onChange(next ?? '')}
      />
    </div>
  );
}
