import { useEffect, useState } from 'react'

import { SETUP_HOTKEY_ROWS } from '@/components/intro/hotkeyDisplay'
import { HotkeyRowView } from '@/components/intro/HotkeyRowView'
import type { HotkeyRowPhase, useSetupHotkeys } from '@/components/intro/useSetupHotkeys'

const IDLE_PHASE: HotkeyRowPhase = { kind: 'idle' }

interface Props {
  hotkeys: ReturnType<typeof useSetupHotkeys>
  /** False when the person unticked the Hotkeys item, so nothing here will be applied. */
  isIncluded: boolean
}

/** The confirm-or-adjust part of express setup for hotkeys: every hotkey with its clash, and the same choices as the step-by-step path. Choices are held until Do it. */
export function ExpressHotkeys({ hotkeys, isIncluded }: Props) {
  const clashCount = hotkeys.rows.filter(row => row.conflicts.length > 0).length
  const [isOpen, setIsOpen] = useState(false)

  // The list opens by itself once, when the check finds a clash, so a clash is never hidden behind a closed list.
  useEffect(() => {
    if (hotkeys.status === 'ready' && clashCount > 0) setIsOpen(true)
    // Only the first load decides this. Fixing a clash must not close the list under the person's hands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotkeys.status])

  if (hotkeys.status !== 'ready') return null

  if (!isIncluded) {
    return <p className="express-note">Your hotkeys are not part of this setup, so I'll leave them as they are.</p>
  }

  const nativeById = new Map(hotkeys.rows.map(row => [row.id, row]))
  const summary = clashCount > 0
    ? `Your hotkeys (${clashCount} ${clashCount === 1 ? 'hotkey clashes' : 'hotkeys clash'} with something on this Mac)`
    : 'Your hotkeys (none clash, but you can change any of them)'

  return (
    <details className="express-hotkeys" open={isOpen} onToggle={event => setIsOpen(event.currentTarget.open)}>
      <summary>{summary}</summary>
      <p className="express-note">Change any of them here. Nothing is saved until you press Do it.</p>
      <dl className="intro-hotkey-list">
        {SETUP_HOTKEY_ROWS.map(row => (
          <HotkeyRowView
            key={row.id}
            id={row.id}
            title={row.title}
            purpose={row.purpose}
            native={nativeById.get(row.id)}
            phase={hotkeys.phases[row.id] ?? IDLE_PHASE}
            hotkeys={hotkeys}
            staged
          />
        ))}
      </dl>
    </details>
  )
}
