import type {
  CheckpointData,
  CheckpointField,
  CheckpointOption,
  WSEvent,
} from '../../types';

// Normalize backend checkpoint options into the frontend CheckpointOption
// shape. Accepts either plain strings ("Option A") or richer objects
// ({ label, value, description, id, variant }) so the UI has a single
// durable model for selectable cards. Invalid/empty entries are dropped.
// This intentionally does NOT inspect prompt text or parse markdown; cards
// render only from explicitly structured options.
function normalizeCheckpointOptions(rawOptions: unknown): CheckpointOption[] | undefined {
  if (!Array.isArray(rawOptions)) return undefined;

  const normalized: CheckpointOption[] = [];
  rawOptions.forEach((raw, index) => {
    if (typeof raw === 'string') {
      const label = raw.trim();
      if (label.length === 0) return;
      normalized.push({ id: `option-${index}`, label, value: label });
      return;
    }

    if (raw && typeof raw === 'object') {
      const obj = raw as Record<string, unknown>;
      const label =
        typeof obj.label === 'string' && obj.label.trim().length > 0
          ? obj.label.trim()
          : typeof obj.value === 'string' && obj.value.trim().length > 0
            ? obj.value.trim()
            : '';
      if (label.length === 0) return;
      const value =
        typeof obj.value === 'string' && obj.value.length > 0
          ? obj.value
          : obj.value && typeof obj.value === 'object'
            ? JSON.stringify(obj.value)
            : label;
      const description =
        typeof obj.description === 'string' && obj.description.trim().length > 0
          ? obj.description.trim()
          : undefined;
      const id =
        typeof obj.id === 'string' && obj.id.length > 0 ? obj.id : `option-${index}`;
      const variant =
        obj.variant === 'primary' || obj.variant === 'warning' || obj.variant === 'danger'
          ? obj.variant
          : 'default';
      normalized.push({ id, label, value, description, variant });
    }
  });

  return normalized.length > 0 ? normalized : undefined;
}

function normalizeCheckpointFields(rawFields: unknown): CheckpointField[] | undefined {
  if (!Array.isArray(rawFields)) return undefined;

  const normalized: CheckpointField[] = [];
  rawFields.forEach(raw => {
    if (!raw || typeof raw !== 'object') return;
    const obj = raw as Record<string, unknown>;
    const name = typeof obj.name === 'string' && obj.name.trim().length > 0 ? obj.name.trim() : '';
    if (name.length === 0) return;
    const label =
      typeof obj.label === 'string' && obj.label.trim().length > 0 ? obj.label.trim() : name;
    const kind = obj.kind === 'choice' ? 'choice' : 'text';
    const required = Boolean(obj.required);
    const defaultValue = typeof obj.default_value === 'string' ? obj.default_value : undefined;

    if (kind === 'choice') {
      const options = normalizeCheckpointOptions(obj.options);
      if (!options) return;
      normalized.push({ name, label, kind, required, default_value: defaultValue, options });
      return;
    }
    normalized.push({ name, label, kind, required, default_value: defaultValue });
  });

  return normalized.length > 0 ? normalized : undefined;
}

export function normalizeCheckpointData(
  agentTaskId: string,
  rawCheckpoint: unknown,
): CheckpointData | undefined {
  if (!rawCheckpoint || typeof rawCheckpoint !== 'object') return undefined;
  const checkpointRecord = rawCheckpoint as Record<string, unknown>;

  const rawPrompt = checkpointRecord.prompt;
  const prompt =
    typeof rawPrompt === 'string' && rawPrompt.trim().length > 0
      ? rawPrompt.trim()
      : 'Agent needs your input';

  // Backend tooling emits a different vocabulary than the frontend's internal
  // CheckpointData['input_type'] union. Map backend names onto the frontend's
  // set so the existing CheckpointFlow branches light up correctly.
  const rawInputType = checkpointRecord.input_type;
  let inputType: CheckpointData['input_type'] = 'data';
  if (
    rawInputType === 'confirmation' ||
    rawInputType === 'choice' ||
    rawInputType === 'file' ||
    rawInputType === 'review' ||
    rawInputType === 'provider_form'
  ) {
    inputType = rawInputType;
  } else if (rawInputType === 'selection') {
    inputType = 'choice';
  } else if (rawInputType === 'yes_no') {
    inputType = 'confirmation';
  } else if (rawInputType === 'text' || rawInputType === 'numeric' || rawInputType === 'voice') {
    inputType = 'data';
  }

  const options = normalizeCheckpointOptions(checkpointRecord.options);
  const fields = normalizeCheckpointFields(checkpointRecord.fields);

  if (inputType === 'provider_form' && !fields) {
    inputType = 'data';
  }

  const rawCheckpointId = checkpointRecord.checkpoint_id;
  const checkpointId =
    typeof rawCheckpointId === 'string' && rawCheckpointId.length > 0
      ? rawCheckpointId
      : `checkpoint-${agentTaskId}`;

  const defaultValue =
    typeof checkpointRecord.default_value === 'string'
      ? checkpointRecord.default_value
      : undefined;

  const metadata: Record<string, unknown> = {};
  if (checkpointRecord.context_summary !== undefined) {
    metadata.context_summary = checkpointRecord.context_summary;
  }
  if (checkpointRecord.metadata && typeof checkpointRecord.metadata === 'object') {
    Object.assign(metadata, checkpointRecord.metadata as Record<string, unknown>);
  }

  const allowMultiple = inputType === 'choice' && checkpointRecord.allow_multiple === true;
  const valueKind: CheckpointData['value_kind'] =
    inputType === 'data' && rawInputType === 'numeric' ? 'numeric' : undefined;

  return {
    checkpoint_id: checkpointId,
    session_agent_task_id: agentTaskId,
    prompt,
    input_type: inputType,
    options,
    ...(allowMultiple ? { allow_multiple: true } : {}),
    ...(valueKind ? { value_kind: valueKind } : {}),
    fields,
    default_value: defaultValue,
    metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
  };
}

export function normalizeCheckpointPayload(
  agentTaskId: string,
  event: WSEvent,
): CheckpointData | undefined {
  return normalizeCheckpointData(
    agentTaskId,
    (event.checkpoint as Record<string, unknown> | undefined) ??
      (event.checkpoint_data as Record<string, unknown> | undefined),
  );
}
