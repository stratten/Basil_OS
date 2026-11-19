// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { LOCAL_SERVER_POLL_MILLISECONDS, LocalServerPanel, localServerIsChanging } from './LocalServerPanel'
import { qrPath } from './LinkQrCode'
import { codeHasExpired } from './LocalServerLink'
import type { CompanionHealth, CompanionInfo, LocalServerInfo, LocalServerInstall } from '../../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: ReturnType<typeof vi.fn<(id: string) => void>>

const COMMAND = "brew install go"
const SOURCE_DOWNLOAD = 'Download https://example.test/releases/bridge (SHA-256 aaaa)'
const SOURCE_BUILD = 'Build from https://example.test/org/bridge.git at commit bbbb, running: go build'

const INSTALL: LocalServerInstall = {
  phase: 'idle',
  message: 'Not prepared yet.',
  ready: false,
  active: false,
  artifact: null,
  requirement: null,
  canInstall: false,
  detail: null,
  requirements: [{ name: 'Go', reason: 'It builds the bridge.', forMethod: 'build', installCommand: COMMAND }],
  artifacts: [{ name: 'Bridge', expects: 'bin/bridge', ready: false, sources: [SOURCE_DOWNLOAD, SOURCE_BUILD] }],
}

const HEALTH: CompanionHealth = { phase: 'starting', message: '', actionKind: null, actionValue: null, actionExpiresAt: null }

const COMPANION: CompanionInfo = {
  status: 'running',
  port: 51234,
  lastError: null,
  logTail: '',
  restartCount: 0,
  startWithBasil: true,
  fixedPort: null,
  secretEnv: [],
  commandSummary: 'bridge 51234',
  hasProbe: true,
  health: HEALTH,
}

function server(install: Partial<LocalServerInstall> | null, health: Partial<CompanionHealth> | null, companion: Partial<CompanionInfo> = {}): LocalServerInfo {
  return {
    commandSummary: 'uv run main.py',
    sourceUrl: null,
    secretEnv: [],
    install: install ? { ...INSTALL, ...install } : null,
    companion: { ...COMPANION, ...companion, health: health ? { ...HEALTH, ...health } : null },
  }
}

function render(localServer: LocalServerInfo, toolCount?: number) {
  act(() => {
    root.render(<LocalServerPanel connectionId="conn-local" localServer={localServer} disabled={false} onTrackRequest={onTrackRequest} toolCount={toolCount} />)
  })
}

function button(label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((candidate) => (candidate.textContent ?? '') === label)
  if (!found) throw new Error(`No button labeled ${label}`)
  return found
}

function sent(type: string): unknown[] {
  return postMessage.mock.calls.map(([message]) => message).filter((message) => (message as { type: string }).type === type)
}

beforeEach(() => {
  vi.useFakeTimers()
  postMessage = vi.fn()
  onTrackRequest = vi.fn<(id: string) => void>()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('setup section', () => {
  it('lists every program, address, hash, commit and command the recipe will use before anything is chosen', () => {
    render(server(INSTALL, null))
    const text = container.textContent ?? ''

    for (const fragment of ['Go', 'It builds the bridge.', COMMAND, 'Bridge', 'bin/bridge', SOURCE_DOWNLOAD, SOURCE_BUILD, 'Not set up yet']) {
      expect(text).toContain(fragment)
    }
    expect(Array.from(container.querySelectorAll('ol[aria-label^="Ways Basil gets Bridge"] li')).map((item) => item.textContent)).toEqual([SOURCE_DOWNLOAD, SOURCE_BUILD])
    expect(sent('requestPrepareLocalServer')).toEqual([])
  })

  it('starts preparing only when the person chooses Prepare, and offers Cancel instead while it works', () => {
    render(server(INSTALL, null))
    act(() => { button('Prepare').click() })

    expect(sent('requestPrepareLocalServer')).toHaveLength(1)
    expect(onTrackRequest).toHaveBeenCalledTimes(1)

    render(server({ phase: 'downloading', active: true, message: 'Downloading Bridge...' }, null))
    expect(container.textContent).toContain('Downloading Bridge...')
    expect(Array.from(container.querySelectorAll('button')).map((item) => item.textContent)).not.toContain('Prepare')
    act(() => { button('Cancel').click() })

    expect(sent('requestCancelPrepareLocalServer')).toHaveLength(1)
  })

  it('shows an Install button with the exact command only for the program that blocks it, and sends that command', () => {
    render(server({ phase: 'needs_requirement', requirement: 'Go', canInstall: true, message: 'Go is not installed.' }, null))
    const install = button('Install Go')

    expect(install.getAttribute('aria-label')).toBe(`Install Go by running ${COMMAND}`)
    act(() => { install.click() })

    expect(sent('requestInstallLocalServerRequirement')).toEqual([
      expect.objectContaining({ connectionId: 'conn-local', name: 'Go', command: COMMAND }),
    ])
  })

  it('tells the person to install by hand when Basil has no install command, and offers no Install button', () => {
    render(server({ phase: 'needs_requirement', requirement: 'Go', canInstall: false, requirements: [{ name: 'Go', reason: 'x', forMethod: 'build', installCommand: null }] }, null))

    expect(container.textContent).toContain('Basil cannot install this one')
    expect(Array.from(container.querySelectorAll('button')).map((item) => item.textContent)).not.toContain('Install Go')
  })

  it('shows a failure as an alert with the details and offers Try again', () => {
    render(server({ phase: 'failed', message: 'Basil could not get Bridge.', detail: 'download failed | build failed' }, null))

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Basil could not get Bridge.')
    expect(container.textContent).toContain('download failed | build failed')
    act(() => { button('Try again').click() })

    expect(sent('requestPrepareLocalServer')).toHaveLength(1)
  })

  it('shows nothing to do once everything is in place and hides the file sources', () => {
    render(server({ phase: 'ready', ready: true, artifacts: [{ name: 'Bridge', expects: 'bin/bridge', ready: true, sources: [SOURCE_DOWNLOAD] }] }, null))

    expect(container.textContent).toContain('Ready')
    expect(container.textContent).toContain('in place')
    expect(container.textContent).not.toContain(SOURCE_DOWNLOAD)
    expect(Array.from(container.querySelectorAll('button')).map((item) => item.textContent)).not.toContain('Prepare')
  })

  it('shows no setup section for a server that has no recipe', () => {
    render(server(null, null))

    expect(container.querySelector('[aria-label="Setup"]')).toBeNull()
  })
})

describe('link section', () => {
  const QR_VALUE = '2@abcdefghijklmnopqrstuvwxyz0123456789,KEY,KEY2,1'

  it('draws the code and says what to do while the program is waiting for it', () => {
    render(server(null, { phase: 'needs_action', message: 'Open the app on your phone and scan.', actionKind: 'qr', actionValue: QR_VALUE }))

    const svg = container.querySelector('svg[role="img"]')
    expect(svg?.getAttribute('aria-label')).toContain('Code to scan')
    expect(svg?.querySelector('path')?.getAttribute('d')?.length).toBeGreaterThan(100)
    expect(container.textContent).toContain('Waiting for you')
    expect(container.textContent).toContain('Open the app on your phone and scan.')
    expect(container.textContent).not.toContain(QR_VALUE)
  })

  it('hides the code once it has expired and says a new one will appear', () => {
    const past = new Date(Date.now() - 60_000).toISOString()
    render(server(null, { phase: 'needs_action', actionKind: 'qr', actionValue: QR_VALUE, actionExpiresAt: past }))

    expect(container.querySelector('svg[role="img"]')).toBeNull()
    expect(container.textContent).toContain('This code has expired')
  })

  it('shows linked and ready with no code', () => {
    render(server(null, { phase: 'ready', message: 'Linked.' }, {}), 3)

    expect(container.textContent).toContain('Linked and ready')
    expect(container.querySelector('svg[role="img"]')).toBeNull()
  })

  it('shows a failed status page as an alert', () => {
    render(server(null, { phase: 'failed', message: 'The program stopped answering.' }))

    expect(container.querySelector('[aria-label="Link"] [role="alert"]')?.textContent).toBe('The program stopped answering.')
  })

  it('shows no link section when the program has no status page', () => {
    render(server(null, null))

    expect(container.querySelector('[aria-label="Link"]')).toBeNull()
  })

  it('computes expiry only from a readable time and never hides a code with none', () => {
    const base: CompanionHealth = { ...HEALTH, phase: 'needs_action', actionKind: 'qr', actionValue: 'x' }

    expect(codeHasExpired({ ...base, actionExpiresAt: null }, Date.now())).toBe(false)
    expect(codeHasExpired({ ...base, actionExpiresAt: 'garbage' }, Date.now())).toBe(false)
    expect(codeHasExpired({ ...base, actionExpiresAt: new Date(Date.now() + 5000).toISOString() }, Date.now())).toBe(false)
  })
})

describe('qrPath', () => {
  it('encodes text into a square of modules, and refuses an empty value', () => {
    const drawn = qrPath('hello')

    expect(drawn?.size).toBeGreaterThanOrEqual(21)
    expect(drawn?.path.startsWith('M')).toBe(true)
    expect(qrPath('')).toBeNull()
  })

  it('refuses text too long to encode instead of throwing', () => {
    expect(qrPath('x'.repeat(10000))).toBeNull()
  })
})

describe('polling and tools', () => {
  it('asks for fresh state every few seconds while a step is changing, and stops when it settles', () => {
    render(server({ phase: 'downloading', active: true }, null))
    act(() => { vi.advanceTimersByTime(LOCAL_SERVER_POLL_MILLISECONDS * 2 + 10) })

    expect(sent('requestRefreshLocalServerStatus')).toHaveLength(2)

    render(server({ phase: 'ready', ready: true }, { phase: 'ready' }))
    act(() => { vi.advanceTimersByTime(LOCAL_SERVER_POLL_MILLISECONDS * 3) })

    expect(sent('requestRefreshLocalServerStatus')).toHaveLength(2)
  })

  it('keeps asking while the program is waiting for the person, and not otherwise', () => {
    expect(localServerIsChanging(server(null, { phase: 'needs_action' }))).toBe(true)
    expect(localServerIsChanging(server(null, { phase: 'starting' }))).toBe(true)
    expect(localServerIsChanging(server(null, { phase: 'ready' }))).toBe(false)
    expect(localServerIsChanging(server(null, { phase: 'failed' }))).toBe(false)
    expect(localServerIsChanging(server({ phase: 'needs_requirement' }, null, { status: 'stopped' }))).toBe(false)
    expect(localServerIsChanging(server(null, null, { status: 'starting' }))).toBe(true)
  })

  it('does not poll a server with nothing changing', () => {
    render(server(null, null, { status: 'stopped' }))
    act(() => { vi.advanceTimersByTime(LOCAL_SERVER_POLL_MILLISECONDS * 3) })

    expect(sent('requestRefreshLocalServerStatus')).toEqual([])
  })

  it('asks for the tools once when the program becomes linked and none are cached, and not again', () => {
    render(server(null, { phase: 'needs_action' }), 0)
    expect(sent('requestRefreshTools')).toEqual([])

    render(server(null, { phase: 'ready' }), 0)
    render(server(null, { phase: 'ready' }), 0)

    expect(sent('requestRefreshTools')).toHaveLength(1)
  })

  it('does not ask for tools that are already there or when the count is unknown', () => {
    render(server(null, { phase: 'ready' }), 4)
    render(server(null, { phase: 'ready' }), undefined)

    expect(sent('requestRefreshTools')).toEqual([])
  })
})
