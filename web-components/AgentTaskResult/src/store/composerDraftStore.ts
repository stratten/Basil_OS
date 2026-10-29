/** Which box a draft belongs to. A note for a run that is still working and a follow-up for one that has finished are different messages, so they are kept apart even for the same chain. */
export type ComposerDraftKind = 'follow-up' | 'note';

/** What the reader has typed into a task's box and not yet sent. */
export interface ComposerDraft {
  /** The editor's own markup, so bold, lists and code blocks come back as they were typed. Empty when only attachments are held. */
  html: string;
  referencePaths: string[];
}

/** Drafts live in the page, not in the box, because a box unmounts whenever its task is switched away from or a prompt takes its place. They are gone when the app quits. */
const draftsByTask = new Map<string, ComposerDraft>();

function entryKey(kind: ComposerDraftKind, taskKey: string): string {
  return `${kind}:${taskKey}`;
}

function store(kind: ComposerDraftKind, taskKey: string, draft: ComposerDraft): void {
  const key = entryKey(kind, taskKey);
  if (draft.html === '' && draft.referencePaths.length === 0) draftsByTask.delete(key);
  else draftsByTask.set(key, draft);
}

/** The unsent draft for this task's box, or nothing when there is none. The result is a copy, so changing it does not change what is stored. */
export function loadComposerDraft(kind: ComposerDraftKind, taskKey: string): ComposerDraft | undefined {
  const draft = draftsByTask.get(entryKey(kind, taskKey));
  return draft ? { html: draft.html, referencePaths: [...draft.referencePaths] } : undefined;
}

/** Keep the box's current markup. `hasText` is false for an editor that only holds empty markup such as a lone line break, which is not a draft. */
export function rememberComposerHtml(kind: ComposerDraftKind, taskKey: string, html: string, hasText: boolean): void {
  const existing = draftsByTask.get(entryKey(kind, taskKey));
  store(kind, taskKey, { html: hasText ? html : '', referencePaths: existing?.referencePaths ?? [] });
}

/** Keep the files attached to the box. */
export function rememberComposerReferences(kind: ComposerDraftKind, taskKey: string, referencePaths: readonly string[]): void {
  const existing = draftsByTask.get(entryKey(kind, taskKey));
  store(kind, taskKey, { html: existing?.html ?? '', referencePaths: [...referencePaths] });
}

/** Drop the draft once it has been sent or the reader has emptied the box. */
export function forgetComposerDraft(kind: ComposerDraftKind, taskKey: string): void {
  draftsByTask.delete(entryKey(kind, taskKey));
}

type DraftDiscardListener = (kind: ComposerDraftKind, taskKey: string) => void;

const discardListeners = new Set<DraftDiscardListener>();

/** Drop a draft because something other than the box itself made it obsolete, such as a follow-up sent by voice, and tell any box that is still showing it to empty itself. Dropping it silently would leave a mounted box displaying text that is no longer stored, which then reappears on the next keystroke. */
export function discardComposerDraft(kind: ComposerDraftKind, taskKey: string): void {
  draftsByTask.delete(entryKey(kind, taskKey));
  for (const listener of [...discardListeners]) listener(kind, taskKey);
}

/** Be told when a draft is discarded from outside its box. Returns the unsubscribe function. */
export function subscribeComposerDraftDiscarded(listener: DraftDiscardListener): () => void {
  discardListeners.add(listener);
  return () => { discardListeners.delete(listener); };
}

/** Carry a draft to a new key when the same chain starts to be identified differently, so it neither stays behind nor comes back later as a ghost. */
export function moveComposerDraft(kind: ComposerDraftKind, fromTaskKey: string, toTaskKey: string): void {
  if (fromTaskKey === toTaskKey) return;
  const draft = draftsByTask.get(entryKey(kind, fromTaskKey));
  if (!draft) return;
  draftsByTask.delete(entryKey(kind, fromTaskKey));
  draftsByTask.set(entryKey(kind, toTaskKey), draft);
}

/** Test seam: forget every stored draft. */
export function resetComposerDrafts(): void {
  draftsByTask.clear();
}
