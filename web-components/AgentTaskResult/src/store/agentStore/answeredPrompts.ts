import type { AnsweredPrompt } from '../../types';

const MAX_REMEMBERED_PROMPTS = 50;

// A recovered checkpoint's id is built from the task id alone, so every recovery in a session shares it. Remembering it would hide a later, genuine recovery, so those are left to the resume-pending guard in hydration.
const RECOVERED_CHECKPOINT_ID_PREFIX = 'recovered-';

/** Adds an answered prompt to the list, keeping the highest revision answered for an id and only the newest entries. */
export function rememberAnsweredPrompt(
  answered: AnsweredPrompt[] | undefined,
  id: string,
  revision?: number,
): AnsweredPrompt[] {
  const current = answered ?? [];
  if (!id || id.startsWith(RECOVERED_CHECKPOINT_ID_PREFIX)) return current;
  const existing = current.find(entry => entry.id === id);
  const highestRevision = Math.max(existing?.revision ?? 0, revision ?? 0);
  const next = current.filter(entry => entry.id !== id);
  next.push(highestRevision > 0 ? { id, revision: highestRevision } : { id });
  return next.slice(-MAX_REMEMBERED_PROMPTS);
}

/** True when this prompt, at this revision, was already answered, so a stale read or replay must not show it again. */
export function isAnsweredPrompt(
  answered: AnsweredPrompt[] | undefined,
  id: string,
  revision?: number,
): boolean {
  const entry = answered?.find(candidate => candidate.id === id);
  if (!entry) return false;
  return (revision ?? 0) <= (entry.revision ?? 0);
}

/** Forgets an answered prompt, for when delivering the answer failed and the prompt must be answerable again. */
export function forgetAnsweredPrompt(answered: AnsweredPrompt[] | undefined, id: string): AnsweredPrompt[] {
  return (answered ?? []).filter(entry => entry.id !== id);
}
