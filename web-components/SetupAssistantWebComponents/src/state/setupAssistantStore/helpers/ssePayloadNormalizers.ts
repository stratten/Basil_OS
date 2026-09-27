/*
 * SSE payload normalizers
 *
 * The backend speaks snake_case over the SSE wire; the store's type
 * surface is camelCase. These helpers do the conversion at the trust
 * boundary so the reducers in this folder stay readable, and they
 * tolerate malformed payloads by returning `undefined` / `null` or
 * dropping bad items rather than throwing.
 *
 * Pure functions, no state. Called only from `setupAgentEventReducer`
 * (the SSE-event sub-reducer in this same `helpers/` folder).
 *
 * Sibling files in the same `helpers/` folder:
 *   - setupAgentEventReducer.ts     (sole consumer of these normalizers)
 *   - messageBubbleHelpers.ts       (bubble-placement helpers)
 *   - proposalAndArtifactHelpers.ts (artifact + proposal/receipt slice mutators)
 *   - agendaHelpers.ts              (agenda slice mutators)
 *
 * The parent `reducer.ts` lives one level up and does NOT depend on
 * this file directly.
 */

import type {
  SetupInlineVisual,
  SetupInlineVisualKind,
  SetupSuggestionChip,
} from '@/types'

import type {
  SetupAgendaConfirmationRequest,
  SetupAgendaItemMark,
  SetupSessionAgendaItem,
  SetupSessionAgendaItemStatus,
} from '../types'


const ALLOWED_AGENDA_KINDS: ReadonlySet<SetupSessionAgendaItem['kind']> = new Set([
  'action',
  'demo',
  'literacy',
  'conversational',
])

const ALLOWED_AGENDA_STATUSES: ReadonlySet<SetupSessionAgendaItemStatus> = new Set([
  'pending',
  'in_progress',
  'completed',
  'skipped',
  'deferred',
])

const ALLOWED_AGENDA_SOURCES: ReadonlySet<SetupSessionAgendaItem['source']> = new Set([
  'catalog',
  'agent',
])

export function normalizeAgendaItemsFromSse(items: unknown): SetupSessionAgendaItem[] {
  if (!Array.isArray(items)) return []
  const normalized: SetupSessionAgendaItem[] = []
  for (const raw of items) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const id = typeof item.id === 'string' ? item.id : ''
    const title = typeof item.title === 'string' ? item.title : ''
    const intent = typeof item.intent === 'string' ? item.intent : ''
    if (!id || !title || !intent) continue
    const kindCandidate = item.kind as SetupSessionAgendaItem['kind']
    const statusCandidate = item.status as SetupSessionAgendaItemStatus
    const sourceCandidate = item.source as SetupSessionAgendaItem['source']
    const kind = ALLOWED_AGENDA_KINDS.has(kindCandidate) ? kindCandidate : 'conversational'
    const status = ALLOWED_AGENDA_STATUSES.has(statusCandidate)
      ? statusCandidate
      : 'pending'
    const source = ALLOWED_AGENDA_SOURCES.has(sourceCandidate)
      ? sourceCandidate
      : 'agent'
    const completionBasisRaw = item.completion_basis
    const completionBasis = typeof completionBasisRaw === 'string'
      ? completionBasisRaw
      : undefined
    normalized.push({ id, title, intent, kind, source, status, completionBasis })
  }
  return normalized
}

export function normalizeAgendaMarkFromSse(
  payload: { id?: unknown; status?: unknown; completion_basis?: unknown } | undefined,
): SetupAgendaItemMark | null {
  if (!payload) return null
  const id = typeof payload.id === 'string' ? payload.id : ''
  if (!id) return null
  const statusCandidate = payload.status as SetupSessionAgendaItemStatus
  if (!ALLOWED_AGENDA_STATUSES.has(statusCandidate)) return null
  const completionBasis = typeof payload.completion_basis === 'string'
    ? payload.completion_basis
    : undefined
  return { id, status: statusCandidate, completionBasis }
}

export function normalizeAgendaConfirmationFromSse(
  payload: unknown,
): SetupAgendaConfirmationRequest | null {
  if (!payload || typeof payload !== 'object') return null
  const raw = payload as Record<string, unknown>
  const id = typeof raw.id === 'string' ? raw.id : ''
  const agendaItemId = typeof raw.agenda_item_id === 'string' ? raw.agenda_item_id : ''
  const prompt = typeof raw.prompt === 'string' ? raw.prompt : ''
  if (!id || !agendaItemId || !prompt) return null
  return {
    id,
    agendaItemId,
    prompt,
    createdAt: new Date().toISOString(),
  }
}

export function normalizeSuggestionChipsFromSse(chips: unknown): SetupSuggestionChip[] {
  if (!Array.isArray(chips)) return []
  const normalized: SetupSuggestionChip[] = []
  for (const raw of chips) {
    if (!raw || typeof raw !== 'object') continue
    const chip = raw as Record<string, unknown>
    const id = typeof chip.id === 'string' ? chip.id : ''
    const label = typeof chip.label === 'string' ? chip.label : ''
    const message = typeof chip.message === 'string' ? chip.message : ''
    if (!id || !label || !message) continue
    const preliminaryStatusMessage = typeof chip.preliminary_status_message === 'string'
      ? chip.preliminary_status_message.trim()
      : null
    normalized.push({
      id,
      label,
      message,
      preliminaryStatusMessage: preliminaryStatusMessage || createChipStatusFallback(label),
    })
  }
  return normalized
}

function createChipStatusFallback(label: string): string {
  return `Getting started on: ${label.replace(/\.$/, '')}.`
}

const ALLOWED_INLINE_VISUAL_KINDS: ReadonlySet<SetupInlineVisualKind> = new Set([
  'screenshot',
  'icon',
  'icon_pair',
  'bubble_sequence',
  'composite',
])

const PATH_SEPARATOR = String.fromCharCode(47)
const BUNDLED_IMAGE_PATH_PREFIX = `${PATH_SEPARATOR}images${PATH_SEPARATOR}`

/*
 * Translate the backend's absolute bundled-image paths (e.g.
 * `/images/setup/menu_bar_idle.png`) into a relative form that works
 * from the setup assistant's WKWebView entry point.
 *
 * The web bundle is loaded as a file:// URL from
 * client/Sources/Resources/SetupAssistantWebAssets/src/entries/
 * setup-assistant.html, so an absolute `src="/images/..."` resolves
 * to filesystem root and 404s. The PNGs actually live two levels up
 * at SetupAssistantWebAssets/images/setup/*.png. This mirrors the
 * `/images/` -> `../../images/` rewrite that scripts/build-setup-
 * assistant-assets.sh applies to statically-bundled asset references
 * during the build — backend-sent paths bypass that rewrite, so we
 * have to do the same translation at the SSE -> store boundary.
 * Keep the prefix assembled above instead of writing it as a string
 * literal in executable code: the build script intentionally rewrites
 * static asset literals inside compiled JS, and this runtime check must
 * keep recognizing backend-sent paths after that rewrite pass.
 *
 * Pure Vite dev mode (`npm run dev` in SetupAssistantWebComponents)
 * also resolves `../../images/setup/foo.png` correctly because the
 * Vite dev server serves the entry HTML from `/src/entries/` and the
 * `public/images/` folder at the server root.
 *
 * Idempotent: paths that don't start with `/images/` (or that are
 * already relative) pass through unchanged, so non-bundled URLs
 * (future absolute http(s) sources, data URIs, etc.) keep working.
 */
export function normalizeBundledImagePath(path: string): string {
  if (path.startsWith(BUNDLED_IMAGE_PATH_PREFIX)) {
    return `..${PATH_SEPARATOR}..${path}`
  }
  return path
}

export function normalizeInlineVisualFromSse(
  payload: unknown,
): SetupInlineVisual | null {
  if (!payload || typeof payload !== 'object') return null
  const raw = payload as Record<string, unknown>
  const id = typeof raw.id === 'string' ? raw.id : ''
  const visualId = typeof raw.visual_id === 'string' ? raw.visual_id : ''
  const webPath = typeof raw.web_path === 'string' ? raw.web_path : ''
  const caption = typeof raw.caption === 'string' ? raw.caption : ''
  const alt = typeof raw.alt === 'string' ? raw.alt : ''
  const kindCandidate = raw.kind as SetupInlineVisualKind
  const kind = ALLOWED_INLINE_VISUAL_KINDS.has(kindCandidate)
    ? kindCandidate
    : 'screenshot'
  if (!id || !visualId || !caption || !alt) return null
  if (kind !== 'bubble_sequence' && !webPath) return null
  const secondaryWebPath = typeof raw.secondary_web_path === 'string'
    ? raw.secondary_web_path
    : null
  const secondaryAlt = typeof raw.secondary_alt === 'string'
    ? raw.secondary_alt
    : null
  const relatedAgendaItemId = typeof raw.related_agenda_item_id === 'string'
    ? raw.related_agenda_item_id
    : null
  const captionOverride = typeof raw.caption_override === 'string'
    ? raw.caption_override
    : null
  return {
    id,
    visualId,
    webPath: normalizeBundledImagePath(webPath),
    secondaryWebPath: secondaryWebPath ? normalizeBundledImagePath(secondaryWebPath) : null,
    caption,
    alt,
    secondaryAlt,
    kind,
    relatedAgendaItemId,
    captionOverride,
  }
}
