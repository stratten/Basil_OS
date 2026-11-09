import { THINKING_MODEL_ID } from './expressTestSupport'

interface ModelRecord {
  status: string
  progress: number
  display_name?: string
  description?: string
}

export function progressWith(models: Record<string, ModelRecord>) {
  return { all_complete: false, models }
}

function thinkingRecord(status: string, progress: number): ModelRecord {
  return { status, progress, display_name: 'Qwen 3.5 9B', description: 'Reasoning model (5.6GB)' }
}

export const THINKING_DOWNLOADING = progressWith({ [THINKING_MODEL_ID]: thinkingRecord('downloading', 40) })
export const THINKING_COMPLETED = progressWith({ [THINKING_MODEL_ID]: thinkingRecord('completed', 100) })
export const THINKING_FAILED = progressWith({ [THINKING_MODEL_ID]: thinkingRecord('error', 12) })
export const NO_MODELS = progressWith({})

export const VOICE_DOWNLOADING = {
  'OpenAI-whisper-tiny.en': { status: 'downloading', progress: 10, display_name: 'Whisper Tiny (English)', description: 'Fast English transcription (151MB)' },
}

export const LOCAL_ACCESS_RESOLVED = {
  access: { mode: 'local', resolved: true, local_model_id: THINKING_MODEL_ID },
}

export const LOCAL_ACCESS_UNRESOLVED = {
  access: { mode: 'local', resolved: false, local_model_id: THINKING_MODEL_ID },
}
