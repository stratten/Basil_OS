import { useSyncExternalStore } from 'react';

export type ChainExpansionMode = 'single' | 'multiple';

// Module-level store for the host-provided "keep several turns open" preference
// (Settings > Appearance, backend field agent_task_chain_expansion). The host
// delivers it with the init message; anything other than "multiple" means one
// earlier turn open at a time, which is the long-standing behavior.
let currentMode: ChainExpansionMode = 'single';
const listeners = new Set<() => void>();

function normalize(mode: string | undefined | null): ChainExpansionMode {
  return mode === 'multiple' ? 'multiple' : 'single';
}

export function applyHostChainExpansion(mode: string | undefined | null): void {
  const next = normalize(mode);
  if (next === currentMode) return;
  currentMode = next;
  listeners.forEach(listener => listener());
}

export function getChainExpansionMode(): ChainExpansionMode {
  return currentMode;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook returning the current chain expansion mode, re-rendering on change. */
export function useChainExpansionMode(): ChainExpansionMode {
  return useSyncExternalStore(subscribe, getChainExpansionMode, getChainExpansionMode);
}
