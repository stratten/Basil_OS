import { useModelDisplayName } from './useModelDisplayName';

/** A quiet label naming the model that answered a run; renders nothing when no model was recorded. */
export function ModelUsedLabel({ modelId, className, prefix }: { modelId?: string; className: string; prefix?: string }) {
  const displayName = useModelDisplayName(modelId);
  if (!displayName) return null;
  return (
    <span className={className} title={`Answered by ${displayName}`}>
      {prefix ? `${prefix} ${displayName}` : displayName}
    </span>
  );
}
