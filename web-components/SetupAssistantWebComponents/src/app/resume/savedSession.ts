import type { SetupAgentModelAccess } from '@/types'
import type {
  SetupAssistantState,
  SetupSessionAgendaItem,
  SetupSessionAgendaItemKind,
  SetupSessionAgendaItemSource,
  SetupSessionAgendaItemStatus,
  SetupStage,
} from '@/state/setupAssistantStore'

// What the backend keeps when someone leaves setup partway: the stage, the agenda, a short summary, and the model they chose. Nothing expires. The age only decides whether the window suggests starting from the top.

export type ResumableStage = Extract<SetupStage, 'orientation' | 'conversation'>

export interface SavedSetupSession {
  stage: ResumableStage
  summary: string
  modelAccess: SetupAgentModelAccess
  interactionStyle: string[]
  agenda: SetupSessionAgendaItem[]
  ageDays: number
  advisoryAfterDays: number
}

export interface SavedSessionFields {
  resume_stage: ResumableStage | null
  resume_summary: string | null
  resume_model_access: SetupAgentModelAccess | null
  resume_interaction_style: string[]
}

const DEFAULT_ADVISORY_AFTER_DAYS = 3
const MAX_SUMMARY_CHARS = 1800
const AGENDA_KINDS: readonly SetupSessionAgendaItemKind[] = ['action', 'demo', 'literacy', 'conversational']
const AGENDA_SOURCES: readonly SetupSessionAgendaItemSource[] = ['catalog', 'agent']
const AGENDA_STATUSES: readonly SetupSessionAgendaItemStatus[] = ['pending', 'in_progress', 'completed', 'skipped', 'deferred']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

function parseAgenda(value: unknown): SetupSessionAgendaItem[] {
  if (!Array.isArray(value)) return []
  const items: SetupSessionAgendaItem[] = []
  for (const entry of value) {
    if (!isRecord(entry) || typeof entry.id !== 'string' || typeof entry.title !== 'string') continue
    // Whatever was being worked on when the window closed is not being worked on now.
    const status = pick(entry.status, AGENDA_STATUSES, 'pending')
    items.push({
      id: entry.id,
      title: entry.title,
      intent: typeof entry.intent === 'string' ? entry.intent : '',
      kind: pick(entry.kind, AGENDA_KINDS, 'conversational'),
      source: pick(entry.source, AGENDA_SOURCES, 'agent'),
      status: status === 'in_progress' ? 'pending' : status,
      ...(typeof entry.completion_basis === 'string' ? { completionBasis: entry.completion_basis } : {}),
    })
  }
  return items
}

/** The saved session in the backend's setup state, or null when there is nothing to continue from. */
export function parseSavedSetupSession(state: Record<string, unknown> | null | undefined): SavedSetupSession | null {
  if (!state || state.completed === true || state.pending_setup_assistant !== true) return null
  const stage = state.resume_stage
  if (stage !== 'orientation' && stage !== 'conversation') return null
  const access = state.resume_model_access
  if (!isRecord(access) || access.resolved !== true || typeof access.mode !== 'string') return null
  const ageDays = typeof state.resume_age_days === 'number' && state.resume_age_days >= 0 ? Math.floor(state.resume_age_days) : 0
  const advisoryAfterDays = typeof state.resume_advisory_after_days === 'number' ? state.resume_advisory_after_days : DEFAULT_ADVISORY_AFTER_DAYS
  return {
    stage,
    summary: typeof state.resume_summary === 'string' ? state.resume_summary : '',
    modelAccess: access as unknown as SetupAgentModelAccess,
    interactionStyle: Array.isArray(state.resume_interaction_style)
      ? state.resume_interaction_style.filter((item): item is string => typeof item === 'string')
      : [],
    agenda: parseAgenda(state.session_goals),
    ageDays,
    advisoryAfterDays,
  }
}

/** True when the saved session is old enough that starting from the top is worth suggesting. */
export function shouldSuggestStartingOver(session: SavedSetupSession): boolean {
  return session.ageDays >= session.advisoryAfterDays
}

export function describeSessionAge(ageDays: number): string {
  if (ageDays <= 0) return 'earlier today'
  if (ageDays === 1) return 'yesterday'
  return `${ageDays} days ago`
}

const STATUS_WORDS: Record<SetupSessionAgendaItemStatus, string> = {
  pending: 'not yet',
  in_progress: 'not yet',
  completed: 'done',
  skipped: 'skipped',
  deferred: 'for later',
}

/** A short plain-text account of what the session had covered, kept with the saved state and read back to the agent on resume. */
export function buildResumeSummary(
  agenda: readonly SetupSessionAgendaItem[],
  savedTitles: readonly string[],
): string {
  const lines: string[] = []
  if (savedTitles.length > 0) {
    lines.push(`Saved so far: ${savedTitles.join('; ')}.`)
  }
  if (agenda.length > 0) {
    lines.push('Agenda:')
    for (const item of agenda) lines.push(`- ${item.title} (${STATUS_WORDS[item.status]})`)
  }
  return lines.join('\n').slice(0, MAX_SUMMARY_CHARS)
}

/** The fields to send with a skip so the session can be picked up later. Empty values when the session was not far enough along to continue. */
export function buildSavedSessionFields(
  state: Pick<SetupAssistantState, 'setupStage' | 'setupAgentModelAccess' | 'sessionAgenda' | 'interactionStyle'>,
  savedTitles: readonly string[],
): SavedSessionFields {
  const stage = state.setupStage
  const canResume = (stage === 'orientation' || stage === 'conversation') && state.setupAgentModelAccess?.resolved === true
  if (!canResume) {
    return { resume_stage: null, resume_summary: null, resume_model_access: null, resume_interaction_style: [] }
  }
  return {
    resume_stage: stage as ResumableStage,
    resume_summary: buildResumeSummary(state.sessionAgenda, savedTitles),
    resume_model_access: state.setupAgentModelAccess,
    resume_interaction_style: state.interactionStyle,
  }
}

/** The first message of a resumed conversation. The agent sees the agenda through the request too, so this only says what happened and what to do. */
export function buildResumeSeedMessage(session: SavedSetupSession): string {
  const lines = [
    `I am coming back to setup after leaving it ${describeSessionAge(session.ageDays)}.`,
    'Pick up where we left off. Do not start over, do not repeat questions already answered, and do not redo anything marked done.',
  ]
  if (session.summary.trim()) {
    lines.push('', 'What we had covered:', session.summary.trim())
  }
  lines.push('', 'Say in one sentence where we are, then continue with the next item that is not done.')
  return lines.join('\n')
}
