import type { StarterDownloadProgress } from '@/services/api'
import type { SetupAgentModelAccessOption } from '@/types'

export type StarterDownloadState = 'pending' | 'downloading' | 'completed' | 'failed'

export interface StarterDownloadRow {
  id: string
  /** The registry model type and variant the download and copy routes take. Empty when the id cannot be split. */
  modelType: string
  variant: string
  /** The model's own name, such as "Whisper Tiny (English)". */
  title: string
  /** What the model is for, such as "Fast voice model". */
  role: string
  /** A plain sentence about what the model does, with its size, such as "Turns your speech into text quickly, in English (151MB)". */
  detail: string
  state: StarterDownloadState
  percent: number
  /** Bytes received and bytes in the whole download, or null while the download has not reported them. */
  downloadedBytes: number | null
  totalBytes: number | null
  /** True for the two voice models. The reasoning model is the one the model step lets the person choose. */
  isVoiceModel: boolean
  /** True only in a validation session whose normal Basil holds this model, so it can be copied instead of downloaded. */
  canCopy: boolean
  /** What the backend is doing right now while the model downloads. The progress bar shows it only until the first bytes arrive. */
  waitingNote?: string | null
}

const VOICE_MODEL_ROLES: Record<string, string> = {
  'OpenAI-whisper-tiny.en': 'Fast voice model',
  'NVIDIA-parakeet-tdt-0.6b-v3-quantized': 'High-quality voice model',
}

export const THINKING_MODEL_ROLE = 'Thinking model'
export const THINKING_MODEL_DETAIL = 'The model that does my thinking'

const VOICE_MODEL_DETAILS: Record<string, string> = {
  'OpenAI-whisper-tiny.en': 'Turns your speech into text quickly, in English',
  'NVIDIA-parakeet-tdt-0.6b-v3-quantized': 'Turns your speech into text with higher quality, in many languages',
}

/** The size the registry puts in brackets at the end of a description, written as " (151MB)", or an empty string when there is none. */
function sizeFromDescription(description: string | undefined): string {
  const match = description?.match(/\(([^()]+)\)\s*$/)
  return match ? ` (${match[1]})` : ''
}

const FAILED_STATUSES: readonly string[] = ['error', 'failed', 'canceled']
const ACTIVE_STATUSES: readonly string[] = ['queued', 'downloading']

/** Maps a backend status string to the four states the panel shows. An unknown status reads as not started. */
export function starterDownloadState(status: string): StarterDownloadState {
  if (status === 'completed' || status === 'skipped_installed') return 'completed'
  if (ACTIVE_STATUSES.includes(status)) return 'downloading'
  if (FAILED_STATUSES.includes(status)) return 'failed'
  return 'pending'
}

/** Splits a registry id such as `NVIDIA-parakeet-tdt-0.6b-v3-quantized` into the model type and variant the download route takes. */
export function splitRegistryId(id: string): { modelType: string, variant: string } | null {
  const separator = id.indexOf('-')
  if (separator <= 0 || separator === id.length - 1) return null
  return { modelType: id.slice(0, separator), variant: id.slice(separator + 1) }
}

/** A byte count the backend reported, or null when it is missing or not a usable number. */
export function reportedBytes(value: number | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(Number.isFinite(value) ? value : 0)))
}

/** Rows for the status panel: voice models first, then the reasoning model, each named by the registry and labeled with its role. */
export function describeStarterDownloads(progress: StarterDownloadProgress): StarterDownloadRow[] {
  const rows = Object.entries(progress.models).map(([id, record]): StarterDownloadRow => {
    const voiceRole = VOICE_MODEL_ROLES[id]
    const parts = splitRegistryId(id)
    return {
      id,
      modelType: parts?.modelType ?? '',
      variant: parts?.variant ?? '',
      title: record.display_name ?? id,
      role: voiceRole ?? THINKING_MODEL_ROLE,
      detail: `${VOICE_MODEL_DETAILS[id] ?? THINKING_MODEL_DETAIL}${sizeFromDescription(record.description)}`,
      state: starterDownloadState(record.status),
      percent: clampPercent(record.progress),
      downloadedBytes: reportedBytes(record.total_downloaded),
      totalBytes: reportedBytes(record.total_size),
      isVoiceModel: voiceRole !== undefined,
      canCopy: record.can_copy_from_normal_basil === true,
      waitingNote: record.message?.trim() || null,
    }
  })
  return rows.sort((a, b) => Number(b.isVoiceModel) - Number(a.isVoiceModel))
}

/** The latest read of one model's own download: its status, how far along it is (0 to 100), and the bytes it has reported. */
export interface LiveLocalDownload {
  status: string
  percent: number
  downloadedBytes: number | null
  totalBytes: number | null
  /** What the backend is doing right now, or null when it did not say. */
  message?: string | null
}

/** The reasoning-model row for the model the Local route describes, or null when the route names no model. `live` is the latest read of that model's own download, when one has been started. */
export function reasoningRowFromOption(
  option: SetupAgentModelAccessOption | undefined,
  live: LiveLocalDownload | null,
): StarterDownloadRow | null {
  if (!option?.local_model_id || !option.local_model_type || !option.local_model_variant) return null
  const size = option.download_size_description ? ` (${option.download_size_description})` : ''
  const state: StarterDownloadState = option.downloaded
    ? 'completed'
    : live ? starterDownloadState(live.status) : 'pending'
  return {
    id: option.local_model_id,
    modelType: option.local_model_type,
    variant: option.local_model_variant,
    title: option.display_name ?? option.local_model_id,
    role: THINKING_MODEL_ROLE,
    detail: `${THINKING_MODEL_DETAIL}${size}`,
    state,
    percent: state === 'downloading' && live ? clampPercent(live.percent) : state === 'completed' ? 100 : 0,
    downloadedBytes: state === 'downloading' && live ? live.downloadedBytes : null,
    totalBytes: state === 'downloading' && live ? live.totalBytes : null,
    isVoiceModel: false,
    canCopy: option.can_copy_from_normal_basil === true,
    waitingNote: state === 'downloading' && live ? live.message?.trim() || null : null,
  }
}

export function isStarterPackFinished(rows: StarterDownloadRow[]): boolean {
  return rows.length > 0 && rows.every(row => row.state === 'completed')
}

/** True while at least one row still needs a poll to learn its outcome. */
export function hasActiveStarterDownload(rows: StarterDownloadRow[]): boolean {
  return rows.some(row => row.state === 'downloading')
}

/** The rows a person can still start: not downloaded yet, or failed and worth retrying. */
export function startableRows(rows: StarterDownloadRow[]): StarterDownloadRow[] {
  return rows.filter(row => row.state === 'pending' || row.state === 'failed')
}
