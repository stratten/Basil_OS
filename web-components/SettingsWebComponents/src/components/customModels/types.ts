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

export interface HFFileOption {
  name: string
  sizeBytes: number | null
  sizeHuman: string | null
}
