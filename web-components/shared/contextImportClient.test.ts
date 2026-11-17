import { afterEach, describe, expect, it, vi } from 'vitest'

import { createContextImportClient } from './contextImportClient'

function response(status: number, body: unknown, rawText?: string) {
  return { ok: status >= 200 && status < 300, status, text: vi.fn().mockResolvedValue(rawText ?? JSON.stringify(body)) }
}

afterEach(() => { vi.unstubAllGlobals() })

describe('createContextImportClient', () => {
  it('starts a records job and a profile job with the bodies the backend expects', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { job_id: 'job-1', chunks_total: 2 }))
      .mockResolvedValueOnce(response(200, { job_id: 'job-2', chunks_total: 1 }))
      .mockResolvedValueOnce(response(200, { job_id: 'job-3', chunks_total: 1 }))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('http://127.0.0.1:8000')
    const access = { mode: 'local' as const, local_model_id: 'qwen', provider: null, model_id: null, resolved: true }

    await client.startRecordsJob('- note', 'a.md', 'a.md')
    await client.startProfileJob('about me', 'p.md', 'p.md', access)
    await client.startProfileJob('about me', '', '')

    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/memory/context-import/jobs/records')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ text: '- note', filename: 'a.md', label: 'a.md' })
    expect(fetchMock.mock.calls[1][0]).toBe('http://127.0.0.1:8000/memory/context-import/jobs/profile')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ text: 'about me', filename: 'p.md', label: 'p.md', model_access: access })
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ text: 'about me', filename: '', label: '' })
  })

  it('sends screenshots to the image route with the confirmed model route, and surfaces the backend explanation on a 400', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { text: 'Be brief.' }))
      .mockResolvedValueOnce(response(400, { detail: 'The model you chose runs on this Mac and can only read text.' }))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('http://127.0.0.1:8000')
    const access = { mode: 'basil_cloud' as const, resolved: true }
    const images = [{ mime_type: 'image/png', data_base64: 'AAAA' }]

    expect(await client.readImages(images, access)).toEqual({ text: 'Be brief.' })
    await expect(client.readImages(images)).rejects.toThrow('can only read text')

    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/memory/context-import/images/read')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ images, model_access: access })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ images })
  })

  it('reads and cancels a job by its encoded id', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { job_id: 'job/1', state: 'running' }))
      .mockResolvedValueOnce(response(200, { job_id: 'job/1', state: 'running' }))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('')

    await client.readJob('job/1')
    await client.cancelJob('job/1')

    expect(fetchMock.mock.calls[0][0]).toBe('/memory/context-import/jobs/job%2F1')
    expect(fetchMock.mock.calls[1][0]).toBe('/memory/context-import/jobs/job%2F1')
    expect(fetchMock.mock.calls[1][1]).toEqual({ method: 'DELETE' })
  })

  it('commits records, commits a profile, and undoes a profile with the backend bodies and paths', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { entries_added: 2 }))
      .mockResolvedValueOnce(response(200, { backup_id: 'profile-abc', files_updated: ['user.md'], label: 'p' }))
      .mockResolvedValueOnce(response(200, { files_restored: ['user.md'] }))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('')

    await client.commit('p1', ['dated', 'stable_fact'])
    await client.commitProfile('draft-1', '- essentials', '')
    await client.undoProfile('profile-abc')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ preview_id: 'p1', categories: ['dated', 'stable_fact'] })
    expect(fetchMock.mock.calls[1][0]).toBe('/memory/context-import/profile/commit')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ draft_id: 'draft-1', essentials_md: '- essentials', user_md: '' })
    expect(fetchMock.mock.calls[2][0]).toBe('/memory/context-import/profile/backups/profile-abc')
    expect(fetchMock.mock.calls[2][1]).toEqual({ method: 'DELETE' })
  })

  it('lists batches and undoes one by its encoded id', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(200, { batches: [{ batch_id: 'import-1', imported_at: 'x', label: 'a', entry_count: 3 }] }))
      .mockResolvedValueOnce(response(200, { entries_removed: 3 }))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('')

    expect(await client.listBatches()).toHaveLength(1)
    await client.undo('import/1')

    expect(fetchMock.mock.calls[1][0]).toBe('/memory/context-import/batches/import%2F1')
    expect(fetchMock.mock.calls[1][1]).toEqual({ method: 'DELETE' })
  })

  it('surfaces the backend detail for a 409, 413 and 422 as the error message', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(409, { detail: 'Another import is still reading.' }))
      .mockResolvedValueOnce(response(413, { detail: 'Too big. Split it.' }))
      .mockResolvedValueOnce(response(422, { detail: [{ loc: ['body'] }] }))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('')

    await expect(client.startRecordsJob('x', '', '')).rejects.toThrow('Another import is still reading.')
    await expect(client.startRecordsJob('x', '', '')).rejects.toThrow('Too big. Split it.')
    await expect(client.startRecordsJob('x', '', '')).rejects.toThrow('The request failed (422).')
  })

  it('reports an unreachable backend and an unreadable response in plain words', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(response(200, null, 'not json'))
    vi.stubGlobal('fetch', fetchMock)
    const client = createContextImportClient('')

    await expect(client.listBatches()).rejects.toThrow('could not reach the memory service')
    await expect(client.listBatches()).rejects.toThrow('could not read the memory service response')
  })
})
