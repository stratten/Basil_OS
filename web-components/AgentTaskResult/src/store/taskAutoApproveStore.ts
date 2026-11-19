import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { getTaskAutoApprove } from '../services/api';
import { registerTaskAutoApproveResultHandler, requestTaskAutoApprove } from '../services/bridge';

/** What a task chain's auto-approve switch looks like to the box showing it. The backend owns the real switch; this is the window's copy of it. */
export interface TaskAutoApproveState {
  enabled: boolean;
  /** A change is with native, which is asking the user to confirm it, or waiting on the backend. */
  pending: boolean;
  /** Set when native could not change the switch. A change the user declined is not an error and leaves nothing here. */
  error: string | null;
}

const OFF: TaskAutoApproveState = { enabled: false, pending: false, error: null };

const stateByChain = new Map<string, TaskAutoApproveState>();
/** Chains whose real state has been read from the backend, so a box mounting again does not read it twice. */
const loadedChains = new Set<string>();
const loadingChains = new Set<string>();
/** Requests native has not answered yet, by request id, with the chain each belongs to. */
const pendingRequests = new Map<string, string>();
const listeners = new Set<() => void>();
let requestCounter = 0;
let stopListening: (() => void) | null = null;

function emit() {
  for (const listener of Array.from(listeners)) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getTaskAutoApproveState(chainKey: string): TaskAutoApproveState {
  return stateByChain.get(chainKey) ?? OFF;
}

function write(chainKey: string, next: TaskAutoApproveState) {
  const previous = getTaskAutoApproveState(chainKey);
  if (previous.enabled === next.enabled && previous.pending === next.pending && previous.error === next.error) return;
  stateByChain.set(chainKey, next);
  emit();
}

function ensureListening() {
  if (stopListening) return;
  stopListening = registerTaskAutoApproveResultHandler((result) => {
    const chainKey = pendingRequests.get(result.requestId);
    if (chainKey === undefined) return;
    pendingRequests.delete(result.requestId);
    loadedChains.add(chainKey);
    write(chainKey, {
      enabled: result.enabled,
      pending: false,
      error: result.status === 'failed' ? result.message || 'Auto-approve could not be changed.' : null,
    });
  });
}

/** Reads the chain's real state once, so a switch turned on earlier shows as on when the box appears again. A failed read leaves the switch off and is tried again the next time a box mounts. */
export async function loadTaskAutoApprove(chainKey: string): Promise<void> {
  if (loadedChains.has(chainKey) || loadingChains.has(chainKey)) return;
  loadingChains.add(chainKey);
  try {
    const { enabled } = await getTaskAutoApprove(chainKey);
    loadedChains.add(chainKey);
    // A change the user made while this read was out is newer than the read.
    if (!getTaskAutoApproveState(chainKey).pending) write(chainKey, { ...getTaskAutoApproveState(chainKey), enabled });
  } catch {
    // The switch stays as it was; there is nothing for the reader to act on.
  } finally {
    loadingChains.delete(chainKey);
  }
}

/** Asks native to turn the switch on or off. Does nothing while an earlier change is still with native. */
export function setTaskAutoApprove(chainKey: string, enabled: boolean): void {
  const current = getTaskAutoApproveState(chainKey);
  if (current.pending || current.enabled === enabled) return;
  ensureListening();
  requestCounter += 1;
  const requestId = `task-auto-approve-${Date.now()}-${requestCounter}`;
  pendingRequests.set(requestId, chainKey);
  write(chainKey, { ...current, pending: true, error: null });
  requestTaskAutoApprove({ requestId, rootTaskId: chainKey, enabled });
}

/** Test seam: forget every chain's switch and every request in flight. */
export function resetTaskAutoApproveStore(): void {
  stateByChain.clear();
  loadedChains.clear();
  loadingChains.clear();
  pendingRequests.clear();
  stopListening?.();
  stopListening = null;
  requestCounter = 0;
  emit();
}

export function useTaskAutoApprove(chainKey: string): TaskAutoApproveState & { setEnabled: (enabled: boolean) => void } {
  const state = useSyncExternalStore(
    subscribe,
    () => getTaskAutoApproveState(chainKey),
    () => OFF,
  );
  useEffect(() => {
    ensureListening();
    void loadTaskAutoApprove(chainKey);
  }, [chainKey]);
  const setEnabled = useCallback((enabled: boolean) => setTaskAutoApprove(chainKey, enabled), [chainKey]);
  return { ...state, setEnabled };
}
