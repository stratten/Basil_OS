export type ContextImportCategory = 'dated' | 'undated' | 'stable_fact'

export interface ContextImportSample {
  title: string
  text: string
  occurred_at: string | null
  section: string
}

export interface ContextImportPreview {
  preview_id: string
  label: string
  source_format: string
  total: number
  counts: Record<ContextImportCategory, number>
  samples: Record<ContextImportCategory, ContextImportSample[]>
  earliest: string | null
  latest: string | null
  warnings: string[]
}

export interface ContextImportCommitResult {
  batch_id: string | null
  label: string
  entries_added: number
  entries_already_present: number
  proposals_queued: number
  proposals_already_known: number
  memory_file_warning: string | null
}

export interface ContextImportBatch {
  batch_id: string
  imported_at: string
  label: string
  entry_count: number
}

/** The setup model route the person confirmed, in the shape the backend's SetupAgentModelAccess expects. */
export interface ImportModelAccess {
  mode: 'local' | 'provider_key' | 'basil_cloud'
  local_model_id?: string | null
  provider?: string | null
  model_id?: string | null
  resolved: boolean
}

export type ImportJobState = 'running' | 'done' | 'failed' | 'canceled'

/** Where a running import is: starting the model, reading the text, combining what it learned (profile only), or writing the result (profile only). */
export type ImportStage = 'loading' | 'reading' | 'combining' | 'writing'

export interface ImportJobStart {
  job_id: string
  chunks_total: number
}

export interface ImportJobStatus<Result> {
  job_id: string
  kind: 'records' | 'profile'
  label: string
  state: ImportJobState
  chunks_done: number
  chunks_total: number
  message: string
  /** Absent from an older backend, which reports only the message. */
  stage?: ImportStage
  /** Roughly how much a local model has written so far, in tokens. Zero for a cloud model, which does not report it. */
  tokens_written?: number
  /** The latest stretch of what a local model is writing, for showing its thinking live. Absent from an older backend, and empty for a cloud model. */
  thinking?: string
  result: Result | null
  error: string | null
}

export interface ProfileDraftFile {
  name: 'essentials.md' | 'user.md'
  current: string
  proposed: string
  cap_bytes: number
}

export interface ProfileDraft {
  draft_id: string
  label: string
  summary: string
  files: ProfileDraftFile[]
  warnings: string[]
}

export interface ProfileCommitResult {
  backup_id: string | null
  files_updated: string[]
  label: string
}

export interface ContextImportClient {
  startRecordsJob(text: string, filename: string, label: string): Promise<ImportJobStart>
  startProfileJob(text: string, filename: string, label: string, modelAccess?: ImportModelAccess | null): Promise<ImportJobStart>
  readJob<Result>(jobId: string): Promise<ImportJobStatus<Result>>
  cancelJob(jobId: string): Promise<void>
  commit(previewId: string, categories: ContextImportCategory[]): Promise<ContextImportCommitResult>
  commitProfile(draftId: string, essentialsMd: string, userMd: string): Promise<ProfileCommitResult>
  undoProfile(backupId: string): Promise<{ files_restored: string[] }>
  listBatches(): Promise<ContextImportBatch[]>
  undo(batchId: string): Promise<{ entries_removed: number }>
}

const UNREACHABLE_MESSAGE = 'Basil could not reach the memory service. Please try again once Basil has finished starting.'
const UNREADABLE_MESSAGE = 'Basil could not read the memory service response. Please try again.'
const BASE_PATH = '/memory/context-import'

async function request<T>(apiBase: string, path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${BASE_PATH}${path}`, init)
  } catch {
    throw new Error(UNREACHABLE_MESSAGE)
  }
  const bodyText = await response.text()
  let body: unknown = null
  try {
    body = bodyText.trim() ? JSON.parse(bodyText) : null
  } catch {
    body = null
  }
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail
    throw new Error(typeof detail === 'string' && detail.trim() ? detail : `The request failed (${response.status}).`)
  }
  if (body === null) throw new Error(UNREADABLE_MESSAGE)
  return body as T
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

/** The one HTTP client for the personal context import, shared by Settings and the setup assistant. */
export function createContextImportClient(apiBase: string): ContextImportClient {
  return {
    startRecordsJob: (text, filename, label) => request<ImportJobStart>(apiBase, '/jobs/records', jsonInit('POST', { text, filename, label })),
    startProfileJob: (text, filename, label, modelAccess) =>
      request<ImportJobStart>(apiBase, '/jobs/profile', jsonInit('POST', { text, filename, label, ...(modelAccess ? { model_access: modelAccess } : {}) })),
    readJob: <Result,>(jobId: string) => request<ImportJobStatus<Result>>(apiBase, `/jobs/${encodeURIComponent(jobId)}`),
    cancelJob: async jobId => {
      await request<unknown>(apiBase, `/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
    },
    commit: (previewId, categories) => request<ContextImportCommitResult>(apiBase, '/commit', jsonInit('POST', { preview_id: previewId, categories })),
    commitProfile: (draftId, essentialsMd, userMd) =>
      request<ProfileCommitResult>(apiBase, '/profile/commit', jsonInit('POST', { draft_id: draftId, essentials_md: essentialsMd, user_md: userMd })),
    undoProfile: backupId => request<{ files_restored: string[] }>(apiBase, `/profile/backups/${encodeURIComponent(backupId)}`, { method: 'DELETE' }),
    listBatches: async () => (await request<{ batches: ContextImportBatch[] }>(apiBase, '/batches')).batches,
    undo: batchId => request<{ entries_removed: number }>(apiBase, `/batches/${encodeURIComponent(batchId)}`, { method: 'DELETE' }),
  }
}
