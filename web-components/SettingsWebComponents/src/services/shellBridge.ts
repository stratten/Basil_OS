import { postToSwiftHandler } from '@shared/swiftBridge'

function postMessage(message: { type: 'close' | 'minimize' | 'collapse' | 'expand' }) {
  postToSwiftHandler('basilSettingsShellBridge', message)
}

export function closeSettingsShell() {
  postMessage({ type: 'close' })
}

export function minimizeSettingsShell() {
  postMessage({ type: 'minimize' })
}

export function collapseSettingsShell() {
  postMessage({ type: 'collapse' })
}

export function expandSettingsShell() {
  postMessage({ type: 'expand' })
}
