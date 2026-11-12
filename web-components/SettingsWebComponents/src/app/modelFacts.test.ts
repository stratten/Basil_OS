import { describe, expect, it } from 'vitest'

import { formatRecommendedMemory, memoryBarFraction, modelFacts, modelFit, parseGigabytes } from './modelFacts'

describe('formatRecommendedMemory', () => {
  it('reads the registry value as a minimum', () => {
    expect(formatRecommendedMemory('16GB')).toBe('16GB or more')
    expect(formatRecommendedMemory('  8GB ')).toBe('8GB or more')
  })
})

describe('memoryBarFraction', () => {
  it('scales gigabytes against a 64GB full bar', () => {
    expect(memoryBarFraction('16GB')).toBe(0.25)
    expect(memoryBarFraction(' 8 gb ')).toBe(0.125)
    expect(memoryBarFraction('48GB')).toBe(0.75)
  })

  it('caps a very large value at a full bar', () => {
    expect(memoryBarFraction('128GB')).toBe(1)
  })

  it('draws no bar for a value that is not a plain gigabyte count', () => {
    expect(memoryBarFraction('')).toBeNull()
    expect(memoryBarFraction('lots')).toBeNull()
    expect(memoryBarFraction('2TB')).toBeNull()
    expect(memoryBarFraction('16GB or more')).toBeNull()
  })
})

describe('modelFacts', () => {
  it('lists speed, quality and memory in the setup comparison wording, each with its bar fill', () => {
    expect(modelFacts({ speedRating: 7, accuracyRating: 8, recommendedRam: '16GB' })).toEqual([
      { label: 'Speed', value: '7 out of 10', fraction: 0.7 },
      { label: 'Quality', value: '8 out of 10', fraction: 0.8 },
      { label: 'Memory', value: '16GB or more', fraction: 0.25 },
    ])
  })

  it('leaves out every fact the registry does not list', () => {
    expect(modelFacts({})).toEqual([])
    expect(modelFacts({ speedRating: 5 })).toEqual([{ label: 'Speed', value: '5 out of 10', fraction: 0.5 }])
    expect(modelFacts({ accuracyRating: 9, recommendedRam: '8GB' })).toEqual([
      { label: 'Quality', value: '9 out of 10', fraction: 0.9 },
      { label: 'Memory', value: '8GB or more', fraction: 0.125 },
    ])
  })

  it('ignores a blank memory value and a rating that is not a number', () => {
    expect(modelFacts({ recommendedRam: '   ' })).toEqual([])
    expect(modelFacts({ recommendedRam: '' })).toEqual([])
    expect(modelFacts({ speedRating: Number.NaN, accuracyRating: Number.POSITIVE_INFINITY })).toEqual([])
  })

  it('keeps a rating of zero instead of treating it as missing, with an empty bar', () => {
    expect(modelFacts({ speedRating: 0 })).toEqual([{ label: 'Speed', value: '0 out of 10', fraction: 0 }])
  })

  it('keeps the text but draws no bar for a memory value it cannot scale', () => {
    expect(modelFacts({ recommendedRam: '2TB' })).toEqual([{ label: 'Memory', value: '2TB or more', fraction: null }])
  })

  it('caps a rating above ten at a full bar', () => {
    expect(modelFacts({ speedRating: 12 })).toEqual([{ label: 'Speed', value: '12 out of 10', fraction: 1 }])
  })
})

describe('modelFacts with this Mac memory', () => {
  it('marks this Mac on the Memory bar and adds a hover note', () => {
    expect(modelFacts({ speedRating: 7, recommendedRam: '16GB' }, 32)).toEqual([
      { label: 'Speed', value: '7 out of 10', fraction: 0.7 },
      { label: 'Memory', value: '16GB or more', fraction: 0.25, markerFraction: 0.5, note: 'This Mac has 32GB', fit: { kind: 'comfortable', verdict: 'Should run well on this Mac.' } },
    ])
  })

  it('keeps the marker on the bar for a Mac with more memory than the bar shows', () => {
    expect(modelFacts({ recommendedRam: '8GB' }, 128)[0].markerFraction).toBe(1)
  })

  it('adds nothing when this Mac memory is unknown, zero, or not a number', () => {
    for (const unknown of [undefined, null, 0, -4, Number.NaN]) {
      const [fact] = modelFacts({ recommendedRam: '16GB' }, unknown)
      expect(fact.markerFraction).toBeUndefined()
      expect(fact.note).toBeUndefined()
      expect(fact.fit).toBeUndefined()
    }
  })

  it('draws no marker when the memory value has no bar', () => {
    expect(modelFacts({ recommendedRam: '2TB' }, 16)).toEqual([{ label: 'Memory', value: '2TB or more', fraction: null, note: 'This Mac has 16GB' }])
  })
})

describe('parseGigabytes', () => {
  it('reads a plain gigabyte count and nothing else', () => {
    expect(parseGigabytes('16GB')).toBe(16)
    expect(parseGigabytes(' 7.5 gb ')).toBe(7.5)
    expect(parseGigabytes('2TB')).toBeNull()
    expect(parseGigabytes('')).toBeNull()
    expect(parseGigabytes(undefined)).toBeNull()
  })
})

describe('modelFit', () => {
  it('is comfortable at or above the recommendation', () => {
    expect(modelFit({ recommendedRam: '16GB' }, 16)).toMatchObject({ kind: 'comfortable' })
    expect(modelFit({ recommendedRam: '16GB' }, 64)).toMatchObject({ kind: 'comfortable' })
  })

  it('is tight from 75 percent of the recommendation up to it', () => {
    expect(modelFit({ recommendedRam: '16GB' }, 12)).toMatchObject({ kind: 'tight' })
    expect(modelFit({ recommendedRam: '16GB' }, 15)).toMatchObject({ kind: 'tight' })
  })

  it('is too large below 75 percent of the recommendation', () => {
    expect(modelFit({ recommendedRam: '16GB' }, 8)).toMatchObject({ kind: 'too_large' })
    expect(modelFit({ recommendedRam: '48GB' }, 16)).toMatchObject({ kind: 'too_large' })
  })

  it('gives each state its own verdict sentence for the hover text', () => {
    expect(modelFit({ recommendedRam: '16GB' }, 8)?.verdict).toBe('Likely too large for this Mac.')
    expect(modelFit({ recommendedRam: '16GB' }, 12)?.verdict).toBe('A tight fit: it may run slowly or fail to load.')
    expect(modelFit({ recommendedRam: '16GB' }, 16)?.verdict).toBe('Should run well on this Mac.')
  })

  it('puts the fit on the Memory fact only, and only when it can be judged', () => {
    expect(modelFacts({ speedRating: 5, recommendedRam: '48GB' }, 12).map((fact) => [fact.label, fact.fit?.kind])).toEqual([['Speed', undefined], ['Memory', 'too_large']])
    expect(modelFacts({ recommendedRam: '2TB' }, 12)[0].fit).toBeUndefined()
  })

  it('shows no indicator when it cannot be sure', () => {
    expect(modelFit({ recommendedRam: '16GB' }, null)).toBeNull()
    expect(modelFit({ recommendedRam: '16GB' }, undefined)).toBeNull()
    expect(modelFit({ recommendedRam: '16GB' }, 0)).toBeNull()
    expect(modelFit({ recommendedRam: undefined }, 16)).toBeNull()
    expect(modelFit({ recommendedRam: '' }, 16)).toBeNull()
    expect(modelFit({ recommendedRam: '2TB' }, 16)).toBeNull()
    expect(modelFit({ recommendedRam: '0GB' }, 16)).toBeNull()
  })
})
