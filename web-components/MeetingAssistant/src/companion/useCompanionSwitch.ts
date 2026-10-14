import { useCallback, useState } from 'react';
import type { CompanionController } from './useCompanion';

/** Drives the Companion switch: turns the Companion on or off and reports `busy` until the backend has answered, so the switch cannot be flipped twice. */
export function useCompanionSwitch(companion: CompanionController) {
  const [busy, setBusy] = useState(false);
  const change = useCallback(
    (next: boolean) => {
      setBusy(true);
      void (next ? companion.enable() : companion.disable()).finally(() => setBusy(false));
    },
    [companion],
  );
  return { busy, change };
}
