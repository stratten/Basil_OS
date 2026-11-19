export interface WizardFeature {
  id: string
  name: string
  isEnabled: boolean
}

export const DEFAULT_FEATURES: WizardFeature[] = [
  { id: 'streaming', name: 'Streaming', isEnabled: true },
  { id: 'system_prompts', name: 'System Prompts', isEnabled: true },
  { id: 'function_calling', name: 'Function Calling', isEnabled: false },
  { id: 'json_mode', name: 'JSON Mode', isEnabled: false },
]

export type ServerType = 'openai_compatible' | 'ollama'

export const SERVER_TYPE_OPTIONS: { value: ServerType; label: string }[] = [
  { value: 'openai_compatible', label: 'Other OpenAI-compatible server' },
  { value: 'ollama', label: 'Ollama' },
]

export const SERVER_TYPE_HINT = 'Choose Ollama so Basil sends this context window to Ollama when it loads the model. Other servers use the context length they were started with, so enter that value above.'

export function serverTypeFrom(value: string | null | undefined): ServerType {
  return value === 'ollama' ? 'ollama' : 'openai_compatible'
}

export interface HFFileOption {
  name: string
  sizeBytes: number | null
  sizeHuman: string | null
}
