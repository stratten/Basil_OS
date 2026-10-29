import { useEffect, useState } from 'react';
import { getReasoningModels } from '../../services/api';

let displayNamesPromise: Promise<Map<string, string>> | null = null;

function loadModelDisplayNames(): Promise<Map<string, string>> {
  if (!displayNamesPromise) {
    displayNamesPromise = getReasoningModels()
      .then(data => new Map(data.models.map(model => [model.id, model.display_name || model.name])))
      .catch(error => {
        // Forget the failure so a later render can retry; the raw id is shown meanwhile.
        displayNamesPromise = null;
        console.error('[useModelDisplayName] Failed to load models:', error);
        return new Map<string, string>();
      });
  }
  return displayNamesPromise;
}

/** Test seam: clears the shared registry cache. */
export function resetModelDisplayNameCache(): void {
  displayNamesPromise = null;
}

/** Resolves a recorded model id to its registry display name, falling back to the raw id and to nothing when no model was recorded. */
export function useModelDisplayName(modelId: string | undefined): string | undefined {
  const [names, setNames] = useState<Map<string, string> | null>(null);

  useEffect(() => {
    if (!modelId) return undefined;
    let canceled = false;
    loadModelDisplayNames().then(loaded => {
      if (!canceled) setNames(loaded);
    });
    return () => {
      canceled = true;
    };
  }, [modelId]);

  if (!modelId) return undefined;
  return names?.get(modelId) ?? modelId;
}
