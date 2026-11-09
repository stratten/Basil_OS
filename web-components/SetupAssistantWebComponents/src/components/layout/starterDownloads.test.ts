import { describe, expect, it } from 'vitest'

import type { SetupAgentModelAccessOption } from '@/types'

import {
  describeStarterDownloads,
  hasActiveStarterDownload,
  isStarterPackFinished,
  reasoningRowFromOption,
  reportedBytes,
  splitRegistryId,
  starterDownloadState,
  startableRows,
} from './starterDownloads'

const PROGRESS = {
  all_complete: false,
  models: {
    'Qwen-qwen35-9b-mlx-4bit': { status: 'downloading', progress: 41.6, description: 'Thinking (6GB)', display_name: 'Qwen3.5-9B MLX 4-bit' },
    'OpenAI-whisper-tiny.en': { status: 'completed', progress: 100, description: 'Fast English transcription (151MB)', display_name: 'Whisper Tiny (English)' },
    'NVIDIA-parakeet-tdt-0.6b-v3-quantized': { status: 'error', progress: 12, description: 'High-quality transcription (670MB)', display_name: 'Parakeet TDT 0.6B v3' },
  },
}

const LOCAL_OPTION: SetupAgentModelAccessOption = {
  mode: 'local',
  available: false,
  requires_provider_key_input: false,
  local_model_id: 'Qwen-qwen35-9b-mlx-4bit',
  local_model_type: 'Qwen',
  local_model_variant: 'qwen35-9b-mlx-4bit',
  display_name: 'Qwen3.5-9B MLX 4-bit',
  download_size_description: '5.6GB',
  downloaded: false,
}

describe('starterDownloadState', () => {
  it.each([
    ['completed', 'completed'],
    ['skipped_installed', 'completed'],
    ['queued', 'downloading'],
    ['downloading', 'downloading'],
    ['error', 'failed'],
    ['failed', 'failed'],
    ['canceled', 'failed'],
    ['pending', 'pending'],
    ['something_new', 'pending'],
    ['', 'pending'],
  ])('maps %s to %s', (status, expected) => {
    expect(starterDownloadState(status)).toBe(expected)
  })
})

describe('describeStarterDownloads', () => {
  it('describes each model in plain words and keeps the size the registry gives', () => {
    expect(describeStarterDownloads(PROGRESS).map(row => row.detail)).toEqual([
      'Turns your speech into text quickly, in English (151MB)',
      'Turns your speech into text with higher quality, in many languages (670MB)',
      'The model that does my thinking (6GB)',
    ])
  })

  it('leaves out the size when the registry gives none, and treats an unknown model as a thinking model', () => {
    const rows = describeStarterDownloads({
      all_complete: false,
      models: {
        'OpenAI-whisper-tiny.en': { status: 'pending', progress: 0, display_name: 'Whisper Tiny (English)' },
        'Acme-new-model': { status: 'pending', progress: 0, description: 'No size here', display_name: 'Acme New' },
      },
    })
    expect(rows.map(row => row.detail)).toEqual([
      'Turns your speech into text quickly, in English',
      'The model that does my thinking',
    ])
  })

  it('lists the voice models before the thinking model, titled by the real model name with the role beside it', () => {
    const rows = describeStarterDownloads(PROGRESS)

    expect(rows.map(row => row.title)).toEqual(['Whisper Tiny (English)', 'Parakeet TDT 0.6B v3', 'Qwen3.5-9B MLX 4-bit'])
    expect(rows.map(row => row.role)).toEqual(['Fast voice model', 'High-quality voice model', 'Thinking model'])
    expect(rows.map(row => row.state)).toEqual(['completed', 'failed', 'downloading'])
    expect(rows.map(row => row.isVoiceModel)).toEqual([true, true, false])
  })

  it('carries the model type and variant the download and copy routes need', () => {
    const rows = describeStarterDownloads(PROGRESS)

    expect(rows[0]).toMatchObject({ modelType: 'OpenAI', variant: 'whisper-tiny.en' })
    expect(rows[2]).toMatchObject({ modelType: 'Qwen', variant: 'qwen35-9b-mlx-4bit' })
  })

  it('falls back to the registry id when the backend sends no name', () => {
    const rows = describeStarterDownloads({ all_complete: false, models: { 'OpenAI-whisper-tiny.en': { status: 'pending', progress: 0 } } })

    expect(rows[0].title).toBe('OpenAI-whisper-tiny.en')
  })

  it('rounds and clamps the percentage, and treats a non-finite value as zero', () => {
    const rows = describeStarterDownloads({
      all_complete: false,
      models: {
        a: { status: 'downloading', progress: 41.6 },
        b: { status: 'downloading', progress: 250 },
        c: { status: 'downloading', progress: Number.NaN },
        d: { status: 'downloading', progress: -5 },
      },
    })

    expect(rows.map(row => row.percent)).toEqual([42, 100, 0, 0])
  })

  it('returns no rows for an empty response and never reports it as finished', () => {
    const rows = describeStarterDownloads({ all_complete: false, models: {} })

    expect(rows).toEqual([])
    expect(isStarterPackFinished(rows)).toBe(false)
  })
})

describe('pack state', () => {
  it('is finished only when every row is completed', () => {
    const rows = describeStarterDownloads(PROGRESS)

    expect(isStarterPackFinished(rows)).toBe(false)
    expect(isStarterPackFinished(rows.map(row => ({ ...row, state: 'completed' as const })))).toBe(true)
  })

  it('reports an active download only while a row is downloading', () => {
    const rows = describeStarterDownloads(PROGRESS)

    expect(hasActiveStarterDownload(rows)).toBe(true)
    expect(hasActiveStarterDownload(rows.filter(row => row.state !== 'downloading'))).toBe(false)
  })
})

describe('reasoningRowFromOption', () => {
  it('builds a not-downloaded row from the Local route option', () => {
    expect(reasoningRowFromOption(LOCAL_OPTION, null)).toMatchObject({
      id: 'Qwen-qwen35-9b-mlx-4bit',
      modelType: 'Qwen',
      variant: 'qwen35-9b-mlx-4bit',
      title: 'Qwen3.5-9B MLX 4-bit',
      role: 'Thinking model',
      detail: 'The model that does my thinking (5.6GB)',
      state: 'pending',
      percent: 0,
      isVoiceModel: false,
    })
  })

  it('reads the live download state and percent, clamped', () => {
    expect(reasoningRowFromOption(LOCAL_OPTION, { status: 'downloading', percent: 41.6, downloadedBytes: null, totalBytes: null })).toMatchObject({ state: 'downloading', percent: 42 })
    expect(reasoningRowFromOption(LOCAL_OPTION, { status: 'downloading', percent: 900, downloadedBytes: null, totalBytes: null })?.percent).toBe(100)
    expect(reasoningRowFromOption(LOCAL_OPTION, { status: 'failed', percent: 12, downloadedBytes: null, totalBytes: null })).toMatchObject({ state: 'failed', percent: 0 })
  })

  it('carries the live byte counts only while the model is downloading', () => {
    const live = { status: 'downloading', percent: 40, downloadedBytes: 2_272_000_000, totalBytes: 5_680_000_000 }
    expect(reasoningRowFromOption(LOCAL_OPTION, live)).toMatchObject({ downloadedBytes: 2_272_000_000, totalBytes: 5_680_000_000 })
    expect(reasoningRowFromOption(LOCAL_OPTION, { ...live, status: 'failed' })).toMatchObject({ downloadedBytes: null, totalBytes: null })
    expect(reasoningRowFromOption(LOCAL_OPTION, null)).toMatchObject({ downloadedBytes: null, totalBytes: null })
  })

  it('treats a downloaded model as ready whatever the live status says', () => {
    expect(reasoningRowFromOption({ ...LOCAL_OPTION, downloaded: true }, { status: 'not_found', percent: 0, downloadedBytes: null, totalBytes: null })).toMatchObject({ state: 'completed', percent: 100 })
  })

  it('returns null when the route names no model, so the step shows no thinking row', () => {
    expect(reasoningRowFromOption(undefined, null)).toBeNull()
    expect(reasoningRowFromOption({ ...LOCAL_OPTION, local_model_id: null }, null)).toBeNull()
    expect(reasoningRowFromOption({ ...LOCAL_OPTION, local_model_variant: null }, null)).toBeNull()
  })

  it('omits the size when the option has none', () => {
    expect(reasoningRowFromOption({ ...LOCAL_OPTION, download_size_description: null }, null)?.detail).toBe('The model that does my thinking')
  })
})

describe('startableRows', () => {
  it('keeps only rows that are not downloaded or that failed', () => {
    const rows = describeStarterDownloads(PROGRESS)

    expect(startableRows(rows).map(row => row.state)).toEqual(['failed'])
    expect(startableRows(rows.map(row => ({ ...row, state: 'pending' as const })))).toHaveLength(3)
    expect(startableRows(rows.map(row => ({ ...row, state: 'completed' as const })))).toEqual([])
  })
})

describe('splitRegistryId', () => {
  it('splits at the first dash so a variant keeps its own dashes', () => {
    expect(splitRegistryId('NVIDIA-parakeet-tdt-0.6b-v3-quantized')).toEqual({ modelType: 'NVIDIA', variant: 'parakeet-tdt-0.6b-v3-quantized' })
    expect(splitRegistryId('OpenAI-whisper-tiny.en')).toEqual({ modelType: 'OpenAI', variant: 'whisper-tiny.en' })
  })

  it.each(['', 'nodash', '-leading', 'trailing-'])('rejects %j', id => {
    expect(splitRegistryId(id)).toBeNull()
  })
})

describe('copy availability', () => {
  it('marks a row copyable only when the backend says the normal Basil holds it', () => {
    const progress = {
      all_complete: false,
      models: {
        'OpenAI-whisper-tiny.en': { status: 'pending', progress: 0, can_copy_from_normal_basil: true },
        'NVIDIA-parakeet-tdt-0.6b-v3-quantized': { status: 'pending', progress: 0, can_copy_from_normal_basil: false },
        'Qwen-qwen35-9b-mlx-4bit': { status: 'pending', progress: 0 },
      },
    }

    const copyable = Object.fromEntries(describeStarterDownloads(progress).map(row => [row.id, row.canCopy]))

    expect(copyable).toEqual({
      'OpenAI-whisper-tiny.en': true,
      'NVIDIA-parakeet-tdt-0.6b-v3-quantized': false,
      'Qwen-qwen35-9b-mlx-4bit': false,
    })
  })

  it('carries the Local route copy flag onto the thinking-model row', () => {
    expect(reasoningRowFromOption({ ...LOCAL_OPTION, can_copy_from_normal_basil: true }, null)?.canCopy).toBe(true)
    expect(reasoningRowFromOption(LOCAL_OPTION, null)?.canCopy).toBe(false)
  })
})

describe('reportedBytes', () => {
  it('accepts a positive number and rejects zero, negatives, missing values and non-numbers', () => {
    expect(reportedBytes(1500)).toBe(1500)
    expect(reportedBytes(0)).toBeNull()
    expect(reportedBytes(-1)).toBeNull()
    expect(reportedBytes(undefined)).toBeNull()
    expect(reportedBytes(Number.NaN)).toBeNull()
    expect(reportedBytes(Number.POSITIVE_INFINITY)).toBeNull()
  })
})

describe('describeStarterDownloads byte counts', () => {
  it('reads the bytes the backend reports for each model and leaves the rest null', () => {
    const rows = describeStarterDownloads({
      all_complete: false,
      models: {
        'OpenAI-whisper-tiny.en': { status: 'downloading', progress: 50, total_downloaded: 75_000_000, total_size: 151_000_000 },
        'NVIDIA-parakeet-tdt-0.6b-v3-quantized': { status: 'pending', progress: 0 },
      },
    })

    expect(rows.find(row => row.id === 'OpenAI-whisper-tiny.en')).toMatchObject({ downloadedBytes: 75_000_000, totalBytes: 151_000_000 })
    expect(rows.find(row => row.id === 'NVIDIA-parakeet-tdt-0.6b-v3-quantized')).toMatchObject({ downloadedBytes: null, totalBytes: null })
  })
})
