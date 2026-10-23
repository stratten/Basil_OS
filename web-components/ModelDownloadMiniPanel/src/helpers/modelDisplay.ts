export interface ModelDisplayInfo {
  title: string
  technicalName: string
}

const knownModelOrder = [
  'OpenAI-whisper-tiny.en',
  'NVIDIA-parakeet-tdt-0.6b-v3-quantized',
  'Qwen-qwen3-8b-instruct-q4km',
]

export function orderModelIds(modelIds: string[]) {
  const known = knownModelOrder.filter(modelId => modelIds.includes(modelId))
  const unknown = modelIds.filter(modelId => !knownModelOrder.includes(modelId)).sort()
  return [...known, ...unknown]
}

export function displayInfoForModel(modelId: string): ModelDisplayInfo {
  if (modelId.includes('whisper-tiny')) {
    return { title: 'Fast Transcription', technicalName: 'Whisper Tiny' }
  }
  if (modelId.includes('parakeet')) {
    return { title: 'Quality Transcription', technicalName: 'Parakeet TDT 0.6B v3' }
  }
  if (modelId.includes('qwen')) {
    return { title: 'Local Reasoning', technicalName: 'Qwen3-8B Q4_K_M' }
  }
  return { title: modelId, technicalName: modelId }
}

export function formatBytes(bytes: number) {
  if (bytes <= 0) return '0 bytes'
  const units = ['bytes', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1000 && unitIndex < units.length - 1) {
    value /= 1000
    unitIndex += 1
  }
  const precision = unitIndex === 0 || value >= 100 ? 0 : 1
  return `${value.toFixed(precision)} ${units[unitIndex]}`
}
