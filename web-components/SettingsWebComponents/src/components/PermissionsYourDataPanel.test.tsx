// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PermissionsYourDataPanel } from './PermissionsYourDataPanel'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

let container: HTMLDivElement
let root: Root
const onShowGrantedPermissions = vi.fn()

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => root.render(<PermissionsYourDataPanel onShowGrantedPermissions={onShowGrantedPermissions} />))
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  onShowGrantedPermissions.mockReset()
})

describe('PermissionsYourDataPanel', () => {
  it('says where Basil keeps its files', () => {
    const text = container.textContent ?? ''
    for (const location of ['~/.basil', '~/.config/basil', '~/Library/Application Support/Basil', 'Your Keychain']) {
      expect(text).toContain(location)
    }
  })

  it('names the uninstaller and all three choices with the options that select them', () => {
    const text = container.textContent ?? ''
    expect(text).toContain('Uninstall Basil.command')
    expect(text).toContain('Everything')
    expect(text).toContain('The app only')
    expect(text).toContain('--app-only')
    expect(text).toContain('Your data only')
    expect(text).toContain('--data-only')
    expect(text).toContain('--dry-run')
    expect(text).toContain('--keep-models')
  })

  it('takes the reader to the list of granted permissions', () => {
    const button = Array.from(container.querySelectorAll('button')).find((candidate) => candidate.textContent === 'See the permissions Basil has')
    expect(button).toBeDefined()
    act(() => button!.click())
    expect(onShowGrantedPermissions).toHaveBeenCalledTimes(1)
  })

  it('changes nothing itself: it has no destructive action and no native bridge call', () => {
    const labels = Array.from(container.querySelectorAll('button')).map((button) => button.textContent)
    expect(labels).toEqual(['See the permissions Basil has'])
    expect(container.querySelector('section')?.getAttribute('aria-labelledby')).toBe('permissions-your-data-heading')
    expect(container.querySelector('#permissions-your-data-heading')?.textContent).toBe('Your Data and Uninstall')
  })
})
