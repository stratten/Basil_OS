import { agentStore } from './agentStore';
import { requestFollowUpLineAdded } from './followUpPrefillStore';
import { submitFollowUpTurn } from '../app/agents/submitFollowUpTurn';
import { userInteractionsFromTimeline } from '../components/interaction/userInteractions';

/** A note meant for a run, as it was sent. */
export interface NoteForRun {
  /** The note as sent to Basil, which is also how it reads in the conversation. */
  text: string;
  referencePaths: string[];
  /** The model the run was using, so the follow-up runs on the same one. */
  modelId?: string;
}

interface SentNote {
  note: NoteForRun;
  /** The task the note was sent to. The conversation is keyed by its root. */
  rootId: string;
  agentTaskId: string;
}

// Notes that Basil accepted for a running task and has not reported reading yet, by note id. They are watched until the run settles them.
const sentNotes = new Map<string, SentNote>();
// Notes that missed their run, by conversation, waiting for the task to finish so that they can go out as a follow-up.
const lateNotes = new Map<string, Array<{ note: NoteForRun; agentTaskId: string }>>();
let unsubscribe: (() => void) | null = null;

function joinNotes(notes: NoteForRun[]): string {
  return notes.map(note => note.text).join('\n\n');
}

function deliverLateNotes(rootId: string): void {
  const waiting = lateNotes.get(rootId);
  if (!waiting || waiting.length === 0) return;
  const agent = agentStore.getAgent(rootId);
  // Wait until the task has finished: a follow-up started earlier would not see the run's final answer.
  if (agent && !agent.isCanceled && agent.status !== 'completed' && agent.status !== 'failed') return;
  lateNotes.delete(rootId);
  const notes = waiting.map(entry => entry.note);
  if (!agent || agent.isCanceled || agent.status === 'failed') {
    // A task that was stopped, ended in failure, or is gone is not continued on the user's behalf. The words go back into the follow-up box to be sent, or not, from there.
    for (const note of notes) requestFollowUpLineAdded(rootId, note.text);
    return;
  }
  const text = joinNotes(notes);
  submitFollowUpTurn({
    content: text,
    displayPromptMarkdown: text,
    referencePaths: [...new Set(notes.flatMap(note => note.referencePaths))],
    rootId,
    agentTaskId: waiting[waiting.length - 1].agentTaskId,
    modelId: notes[notes.length - 1].modelId,
  });
}

function settleSentNotes(): void {
  for (const [noteId, sent] of [...sentNotes]) {
    const agent = agentStore.getAgent(sent.rootId);
    if (!agent) continue;
    const entry = userInteractionsFromTimeline(agent.executionTimeline).find(
      interaction => interaction.kind === 'guidance' && interaction.id === noteId,
    );
    if (!entry || entry.status === 'waiting') continue;
    sentNotes.delete(noteId);
    // Read at its next step: nothing more to do. Not delivered because the run finished first: it goes out as a follow-up.
    if (entry.status === 'canceled') holdNoteForFollowUp(sent.rootId, sent.agentTaskId, sent.note);
  }
}

function react(): void {
  settleSentNotes();
  for (const rootId of [...lateNotes.keys()]) deliverLateNotes(rootId);
  if (sentNotes.size === 0 && lateNotes.size === 0 && unsubscribe) {
    unsubscribe();
    unsubscribe = null;
  }
}

function watchTheStore(): void {
  if (!unsubscribe) unsubscribe = agentStore.subscribe(react);
}

/** Basil accepted this note for a running task. If the run ends without reading it, the note goes out as a follow-up. */
export function trackSentNote(noteId: string, rootId: string, agentTaskId: string, note: NoteForRun): void {
  sentNotes.set(noteId, { note, rootId, agentTaskId });
  watchTheStore();
}

/** This note missed its run. It goes out as a follow-up on the same conversation as soon as the task has finished. */
export function holdNoteForFollowUp(rootId: string, agentTaskId: string, note: NoteForRun): void {
  const waiting = lateNotes.get(rootId) ?? [];
  lateNotes.set(rootId, [...waiting, { note, agentTaskId }]);
  watchTheStore();
  deliverLateNotes(rootId);
}

/** Test seam: forget every watched and waiting note. */
export function resetLateNotes(): void {
  sentNotes.clear();
  lateNotes.clear();
  unsubscribe?.();
  unsubscribe = null;
}
