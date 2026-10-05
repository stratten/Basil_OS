import type { ThinkingSegment, TimelineEntry } from '../../types';

export type UserInteractionKind =
  | 'clarification'
  | 'approval'
  | 'credential'
  | 'provider_target'
  | 'command_input'
  | 'provider_input'
  | 'provider_permission';

export type UserInteractionStatus =
  | 'waiting'
  | 'answered'
  | 'dismissed'
  | 'approved'
  | 'denied'
  | 'timed_out'
  | 'cancelled'
  | 'resolved'
  | 'unrecorded';

export interface UserInteraction {
  id: string;
  entryId: string;
  kind: UserInteractionKind;
  status: UserInteractionStatus;
  prompt: string;
  askedAt: string;
  response?: string;
  responseHidden: boolean;
  respondedAt?: string;
  options: string[];
}

export type ReasoningBlock =
  | { type: 'reasoning'; key: string; segments: ThinkingSegment[] }
  | { type: 'interaction'; key: string; interaction: UserInteraction };

const KINDS: ReadonlySet<string> = new Set([
  'clarification',
  'approval',
  'credential',
  'provider_target',
  'command_input',
  'provider_input',
  'provider_permission',
]);

const STATUSES: ReadonlySet<string> = new Set([
  'waiting',
  'answered',
  'dismissed',
  'approved',
  'denied',
  'timed_out',
  'cancelled',
  'resolved',
]);

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function recordedInteraction(entry: TimelineEntry): UserInteraction | null {
  if (entry.detail_kind !== 'user_interaction') return null;
  const raw = entry.metadata?.user_interaction;
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, unknown>;
  const kind = text(record.kind);
  const status = text(record.status);
  if (!kind || !KINDS.has(kind) || !status || !STATUSES.has(status)) return null;
  return {
    id: text(record.interaction_id) || entry.id || entry.timestamp,
    entryId: entry.id || entry.timestamp,
    kind: kind as UserInteractionKind,
    status: status as UserInteractionStatus,
    prompt: text(record.prompt) || entry.content || '',
    askedAt: text(record.asked_at) || entry.timestamp,
    response: typeof record.response === 'string' ? record.response : undefined,
    responseHidden: record.response_hidden === true,
    respondedAt: text(record.responded_at),
    options: Array.isArray(record.options) ? record.options.filter((option): option is string => typeof option === 'string') : [],
  };
}

function legacyClarification(entry: TimelineEntry): UserInteraction | null {
  if (entry.detail_kind !== 'tool_input' || entry.metadata?.tool_name !== 'request_user_input') return null;
  let prompt = '';
  try {
    const parsed = JSON.parse(entry.body || '') as { prompt?: unknown };
    prompt = text(parsed.prompt) || '';
  } catch {
    prompt = '';
  }
  if (!prompt) return null;
  const entryId = entry.id || entry.timestamp;
  return {
    id: entryId,
    entryId,
    kind: 'clarification',
    status: 'unrecorded',
    prompt: prompt.replace(/\\n/g, '\n'),
    askedAt: entry.timestamp,
    responseHidden: false,
    options: [],
  };
}

/** Return the ask/response exchanges recorded in a task timeline, oldest first. Tasks recorded before exchanges were persisted fall back to their clarification questions, without answers. */
export function userInteractionsFromTimeline(timeline: TimelineEntry[] | undefined): UserInteraction[] {
  const entries = timeline || [];
  const recorded = entries.map(recordedInteraction).filter((interaction): interaction is UserInteraction => interaction !== null);
  const interactions = recorded.length > 0
    ? recorded
    : entries.map(legacyClarification).filter((interaction): interaction is UserInteraction => interaction !== null);
  return interactions
    .map((interaction, index) => ({ interaction, index }))
    .sort((left, right) => {
      const leftTime = Date.parse(left.interaction.askedAt);
      const rightTime = Date.parse(right.interaction.askedAt);
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return leftTime - rightTime;
      return left.index - right.index;
    })
    .map(({ interaction }) => interaction);
}

/** Interleave reasoning passes with the exchanges that happened between them. A pass without a recorded time is placed after every exchange, because such passes only survive from the final resumed run. */
export function splitReasoningAroundInteractions(
  segments: ThinkingSegment[],
  interactions: UserInteraction[],
): ReasoningBlock[] {
  const slots: ThinkingSegment[][] = interactions.map(() => []);
  slots.push([]);
  for (const segment of segments) {
    const recordedTime = segment.recordedAt ? Date.parse(segment.recordedAt) : Number.NaN;
    let slot = interactions.length;
    if (Number.isFinite(recordedTime)) {
      const nextIndex = interactions.findIndex(interaction => {
        const askedTime = Date.parse(interaction.askedAt);
        return Number.isFinite(askedTime) && recordedTime <= askedTime;
      });
      slot = nextIndex === -1 ? interactions.length : nextIndex;
    }
    slots[slot].push(segment);
  }

  const blocks: ReasoningBlock[] = [];
  slots.forEach((slotSegments, index) => {
    if (slotSegments.length > 0) {
      blocks.push({ type: 'reasoning', key: `reasoning-${index}`, segments: slotSegments });
    }
    const interaction = interactions[index];
    if (interaction) blocks.push({ type: 'interaction', key: `interaction-${interaction.entryId}`, interaction });
  });
  return blocks;
}

export function isApprovalLikeInteraction(interaction: Pick<UserInteraction, 'kind'>): boolean {
  return interaction.kind === 'approval' || interaction.kind === 'provider_permission';
}

export function interactionAskerLabel(interaction: Pick<UserInteraction, 'kind'>): string {
  switch (interaction.kind) {
    case 'approval':
      return 'Basil asked to run';
    case 'credential':
      return 'Basil asked for Keychain access';
    case 'provider_target':
      return 'Basil asked you to confirm';
    case 'command_input':
      return 'A command asked you';
    case 'provider_input':
      return 'A provider asked you';
    case 'provider_permission':
      return 'A provider asked permission';
    default:
      return 'Basil asked';
  }
}

export function interactionResponseLabel(interaction: Pick<UserInteraction, 'status' | 'response' | 'responseHidden'>): string {
  switch (interaction.status) {
    case 'waiting':
      return 'Waiting for your answer';
    case 'answered':
      return interaction.responseHidden ? 'You answered (hidden)' : 'You answered';
    case 'dismissed':
      return 'You closed this without answering';
    case 'approved':
      return 'You approved';
    case 'denied':
      return 'You declined';
    case 'timed_out':
      return 'No answer before the time limit';
    case 'cancelled':
      return 'This request was cancelled';
    case 'unrecorded':
      return 'Your answer was not recorded for this task';
    default:
      return 'You responded';
  }
}

const STATUSES_WITH_RESPONSE_TEXT: ReadonlySet<UserInteraction['status']> = new Set([
  'answered',
  'approved',
  'denied',
  'resolved',
]);

export function visibleInteractionResponse(
  interaction: Pick<UserInteraction, 'status' | 'response' | 'responseHidden'>,
): string | null {
  if (interaction.responseHidden || !STATUSES_WITH_RESPONSE_TEXT.has(interaction.status)) return null;
  const response = interaction.response?.trim();
  return response ? response : null;
}

function truncate(value: string, limit: number): string {
  const singleLine = value.replace(/\s+/g, ' ').trim();
  return singleLine.length > limit ? `${singleLine.slice(0, limit - 1)}…` : singleLine;
}

export function interactionSummary(interaction: UserInteraction): string {
  const asked = `${interactionAskerLabel(interaction)}: ${truncate(interaction.prompt, 90)}`;
  const response = visibleInteractionResponse(interaction);
  const answer = response
    ? `${interactionResponseLabel(interaction)}: ${truncate(response, 90)}`
    : interactionResponseLabel(interaction);
  return `${asked}\n${answer}`;
}
