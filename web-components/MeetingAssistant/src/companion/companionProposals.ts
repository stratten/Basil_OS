import type { CompanionTimelineState } from './companionReducer';
import type { CompanionItem, CompanionProposalAction } from './types';

/** The backend refuses a longer question (`MAX_QUESTION_CHARS` in the investigator models). */
export const MAX_INVESTIGATION_QUESTION_CHARS = 300;
/** The most context text one Assistant Session hand-off carries. */
export const MAX_ASSISTANT_CONTEXT_CHARS = 4000;

const INVESTIGATION_PURPOSE = 'investigation';

export const PROPOSAL_ACTION_LABELS: Record<CompanionProposalAction, string> = {
  todo: 'To-Do',
  agent_task: 'Agent Task',
  assistant_session: 'Assistant Session',
};

export interface InvestigationStart {
  id: string;
  question: string;
}

/** Only notes the Companion made on its own can be investigated; an answer that is already researched or a proposal card cannot. */
export function canInvestigate(item: CompanionItem): boolean {
  return item.kind !== 'proposal' && item.researched !== true && !item.dismissed;
}

/** The note's text as a one-line question, cut at a word boundary to the backend's limit. */
export function investigationQuestionFromItem(item: CompanionItem): string {
  const flat = item.text.replace(/\s+/g, ' ').trim();
  if (flat.length <= MAX_INVESTIGATION_QUESTION_CHARS) return flat;
  const head = flat.slice(0, MAX_INVESTIGATION_QUESTION_CHARS);
  const lastSpace = head.lastIndexOf(' ');
  return (lastSpace > MAX_INVESTIGATION_QUESTION_CHARS / 2 ? head.slice(0, lastSpace) : head).trim();
}

/** Every investigation the timeline recorded the start of, oldest first. */
export function investigationStarts(timeline: CompanionTimelineState): InvestigationStart[] {
  const starts: InvestigationStart[] = [];
  for (const event of timeline.retrievals) {
    const payload = event.payload;
    if (typeof payload !== 'object' || payload === null || payload.purpose !== INVESTIGATION_PURPOSE) continue;
    const id = payload.investigation_id;
    if (typeof id !== 'string' || id === '') continue;
    const queries = payload.queries;
    const question = Array.isArray(queries) && typeof queries[0] === 'string' ? queries[0] : '';
    starts.push({ id, question });
  }
  return starts;
}

/** Investigations that started and have produced no item yet. An automatic run that found nothing also leaves no item, so this is a superset of what is running and is only used to pick ids to cancel and a question to show. */
export function unresolvedInvestigations(timeline: CompanionTimelineState): InvestigationStart[] {
  const finished = new Set(timeline.items.map((item) => item.investigation_id).filter((id): id is string => typeof id === 'string'));
  return investigationStarts(timeline).filter((start) => !finished.has(start.id));
}

/** The text of the answer an investigation produced, used as the context an Assistant Session starts from. */
export function proposalContextText(items: CompanionItem[], proposalItem: CompanionItem): string {
  const investigationId = proposalItem.investigation_id;
  if (typeof investigationId !== 'string') return '';
  const answer = items.find((item) => item.investigation_id === investigationId && item.kind !== 'proposal');
  return answer ? answer.text.trim().slice(0, MAX_ASSISTANT_CONTEXT_CHARS) : '';
}
