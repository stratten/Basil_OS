import type { CompanionTimelineState } from './companionReducer';
import { MAX_INVESTIGATION_QUESTION_CHARS, unresolvedInvestigations } from './companionProposals';
import type { ChatMessage } from './types';

/** An answer the Companion cited its sources in carries a marker like `[path/file.py:3-9]`. */
const CITATION_MARKER = /\[[^\]\n]+:\d+(?:-\d+)?\]/;
/** What the Companion says when it has already started or refused a search, so the button would only repeat it. */
const STARTED_REPLY_PREFIX = 'Looking into:';
const STARTED_REPLY_NOTE = "I'm looking into this in your sources";

export interface ChatResearchTarget {
  question: string;
  replyToMessageId: string;
}

function flatten(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

function cut(text: string): string {
  const flat = flatten(text);
  if (flat.length <= MAX_INVESTIGATION_QUESTION_CHARS) return flat;
  const head = flat.slice(0, MAX_INVESTIGATION_QUESTION_CHARS);
  const lastSpace = head.lastIndexOf(' ');
  return (lastSpace > MAX_INVESTIGATION_QUESTION_CHARS / 2 ? head.slice(0, lastSpace) : head).trim();
}

/**
 * What "Look into this" would research for an assistant message, or null when the button should not show.
 *
 * It covers the answers the Companion gave without citing anything, which includes a local model that never writes the research marker. The question is the reader's message the answer replied to (the nearest earlier one). It is not offered for an error, a cut-off answer, an answer that cited its sources, a reply that already started a search, a question already researched, or one being researched now.
 */
export function chatResearchTarget(timeline: CompanionTimelineState, message: ChatMessage): ChatResearchTarget | null {
  if (message.role !== 'assistant' || message.status !== 'complete' || message.truncated) return null;
  const text = message.text.trim();
  if (text === '' || CITATION_MARKER.test(text) || text.startsWith(STARTED_REPLY_PREFIX) || text.includes(STARTED_REPLY_NOTE)) return null;
  let question: ChatMessage | null = null;
  for (const candidate of timeline.chat) {
    if (candidate.role === 'user' && candidate.seq < message.seq && (question === null || candidate.seq > question.seq)) question = candidate;
  }
  if (question === null) return null;
  if (timeline.items.some((item) => item.reply_to_message_id === question.id)) return null;
  const asked = cut(question.text);
  if (asked === '') return null;
  if (unresolvedInvestigations(timeline).some((start) => flatten(start.question) === asked)) return null;
  return { question: asked, replyToMessageId: question.id };
}

/** The reader's question an item answers, for the quote above a researched answer. Null when the message is gone. */
export function replyQuote(timeline: CompanionTimelineState, replyToMessageId: string | null | undefined): string | null {
  if (!replyToMessageId) return null;
  const message = timeline.chat.find((candidate) => candidate.id === replyToMessageId && candidate.role === 'user');
  return message ? cut(message.text) : null;
}
