import { useSyncExternalStore } from 'react';

/** What the follow-up box should do with a request's text. `replace` makes it the whole draft; `add` and `remove` change one line and keep the rest of what the reader wrote. */
export type FollowUpPrefillMode = 'replace' | 'add' | 'remove';

/** A request to change the text in a chain's follow-up box without sending it. */
export interface FollowUpPrefillRequest {
  text: string;
  mode: FollowUpPrefillMode;
  /** Distinguishes two requests for the same text, so choosing the same chip twice still changes the box. */
  nonce: number;
}

const requestsByTask = new Map<string, FollowUpPrefillRequest>();
const draftsByTask = new Map<string, string>();
const listeners = new Set<() => void>();
let nextNonce = 1;

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function queueRequest(taskKey: string, text: string, mode: FollowUpPrefillMode): void {
  requestsByTask.set(taskKey, { text, mode, nonce: nextNonce++ });
  emit();
}

/** Ask the follow-up box of this chain to hold `text` as its whole editable draft. The box consumes the request, so a box that mounts later still receives it. */
export function requestFollowUpPrefill(taskKey: string, text: string): void {
  queueRequest(taskKey, text, 'replace');
}

/** Ask the follow-up box to add `text` as its own line, keeping whatever else is already in the draft. */
export function requestFollowUpLineAdded(taskKey: string, text: string): void {
  queueRequest(taskKey, text, 'add');
}

/** Ask the follow-up box to drop the line that is exactly `text`, keeping the rest of the draft. */
export function requestFollowUpLineRemoved(taskKey: string, text: string): void {
  queueRequest(taskKey, text, 'remove');
}

export function consumeFollowUpPrefill(taskKey: string, nonce: number): void {
  if (requestsByTask.get(taskKey)?.nonce !== nonce) return;
  requestsByTask.delete(taskKey);
  emit();
}

export function useFollowUpPrefillRequest(taskKey: string): FollowUpPrefillRequest | undefined {
  return useSyncExternalStore(
    subscribe,
    () => requestsByTask.get(taskKey),
    () => undefined,
  );
}

/** The follow-up box reports its current plain text here so other surfaces, such as the suggested chips, can show what is in it. */
export function reportFollowUpDraft(taskKey: string, text: string): void {
  if ((draftsByTask.get(taskKey) ?? '') === text) return;
  if (text === '') draftsByTask.delete(taskKey);
  else draftsByTask.set(taskKey, text);
  emit();
}

export function useFollowUpDraft(taskKey: string): string {
  return useSyncExternalStore(
    subscribe,
    () => draftsByTask.get(taskKey) ?? '',
    () => '',
  );
}

/** Test seam: forget every pending request and reported draft. */
export function resetFollowUpPrefillRequests(): void {
  requestsByTask.clear();
  draftsByTask.clear();
  emit();
}
