import type { ModelSummary } from '../types'

/** A comparison fact for a model row. `fraction` is how full its bar is, from 0 to 1, or null when no bar can be drawn. `markerFraction`, `note` and `fit` are only set on the Memory fact when this Mac's memory is known: where that memory falls on the bar, extra hover text, and whether the model fits. */
export interface ModelFact {
  label: string
  value: string
  fraction: number | null
  markerFraction?: number
  note?: string
  fit?: ModelFit
}

/** How well a model's memory recommendation fits this Mac. */
export type ModelFitKind = 'comfortable' | 'tight' | 'too_large'

export interface ModelFit {
  kind: ModelFitKind
  /** The sentence added to the Memory hover text, such as "Likely too large for this Mac." */
  verdict: string
}

/** A memory bar is full at this many gigabytes, which sits above the largest recommendation in the registry. */
export const MEMORY_BAR_FULL_GIGABYTES = 64

/** A model whose recommendation is at most this much larger than this Mac's memory is called a tight fit rather than too large. */
export const TIGHT_FIT_MINIMUM_RATIO = 0.75

/** Memory wording shared with the setup model comparison: "16GB" reads as "16GB or more". */
export function formatRecommendedMemory(recommendedRam: string): string {
  return `${recommendedRam.trim()} or more`
}

function isRating(value: number | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function clampFraction(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/** The gigabyte count in a registry value such as "16GB", or null when the value is not a plain gigabyte count. */
export function parseGigabytes(recommendedRam: string | undefined): number | null {
  if (!recommendedRam) return null
  const match = /^\s*(\d+(?:\.\d+)?)\s*GB\s*$/i.exec(recommendedRam)
  return match ? Number(match[1]) : null
}

/** How full the memory bar is for a registry value such as "16GB". Null when the value is not a plain gigabyte count. */
export function memoryBarFraction(recommendedRam: string): number | null {
  const gigabytes = parseGigabytes(recommendedRam)
  return gigabytes === null ? null : clampFraction(gigabytes / MEMORY_BAR_FULL_GIGABYTES)
}

function isKnownDeviceMemory(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

/**
 * The comparison facts a model row shows, in the same words as the setup model comparison: speed and quality as "N out
 * of 10" and memory as "X or more", each with the fraction its bar is filled. A fact the registry does not list is left
 * out, so a model with none of them, such as a cloud model, shows no facts at all. When this Mac's memory is known, the
 * Memory fact also carries where that memory falls on its bar and a hover note.
 */
export function modelFacts(
  model: Pick<ModelSummary, 'speedRating' | 'accuracyRating' | 'recommendedRam'>,
  deviceMemoryGb?: number | null,
): ModelFact[] {
  const facts: ModelFact[] = []
  if (isRating(model.speedRating)) facts.push({ label: 'Speed', value: `${model.speedRating} out of 10`, fraction: clampFraction(model.speedRating / 10) })
  if (isRating(model.accuracyRating)) facts.push({ label: 'Quality', value: `${model.accuracyRating} out of 10`, fraction: clampFraction(model.accuracyRating / 10) })
  if (model.recommendedRam && model.recommendedRam.trim()) {
    const fraction = memoryBarFraction(model.recommendedRam)
    const memoryFact: ModelFact = { label: 'Memory', value: formatRecommendedMemory(model.recommendedRam), fraction }
    if (isKnownDeviceMemory(deviceMemoryGb)) {
      memoryFact.note = `This Mac has ${deviceMemoryGb}GB`
      if (fraction !== null) memoryFact.markerFraction = clampFraction(deviceMemoryGb / MEMORY_BAR_FULL_GIGABYTES)
      const fit = modelFit(model, deviceMemoryGb)
      if (fit) memoryFact.fit = fit
    }
    facts.push(memoryFact)
  }
  return facts
}

/**
 * Whether this Mac has the memory a model recommends: comfortable at or above the recommendation, tight from 75% of it,
 * and too large below that. Null, so no indicator is shown, when this Mac's memory is unknown or the model lists no
 * recommendation in plain gigabytes, because guessing would put a wrong claim next to a download button.
 */
export function modelFit(model: Pick<ModelSummary, 'recommendedRam'>, deviceMemoryGb?: number | null): ModelFit | null {
  const recommended = parseGigabytes(model.recommendedRam)
  if (recommended === null || recommended <= 0 || !isKnownDeviceMemory(deviceMemoryGb)) return null
  if (deviceMemoryGb >= recommended) return { kind: 'comfortable', verdict: 'Should run well on this Mac.' }
  if (deviceMemoryGb / recommended >= TIGHT_FIT_MINIMUM_RATIO) return { kind: 'tight', verdict: 'A tight fit: it may run slowly or fail to load.' }
  return { kind: 'too_large', verdict: 'Likely too large for this Mac.' }
}
