import { useCallback, useEffect, useRef, useState } from 'react'

import { useSetupHotkeys } from '@/components/intro/useSetupHotkeys'
import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import { applyExpressPlan, fetchExpressPlan } from '@/services/api'
import type { SetupAgentModelAccess } from '@/types'

import { ExpressProgress } from './ExpressProgress'
import { ExpressReview } from './ExpressReview'
import { HOTKEYS_ITEM_ID, type NativeExpressContext } from './expressNativeHotkeys'
import { selectedItemIds, visibleItems } from './expressPlan'
import type { ComfortLevel, ExpressApplyResult, ExpressItemResult, ExpressPlan } from './expressTypes'

const NO_NATIVE_ITEMS: ReadonlySet<string> = new Set()

type LoadState =
  | { phase: 'loading' }
  | { phase: 'error', message: string }
  | { phase: 'ready', plan: ExpressPlan }

interface Props {
  comfort: ComfortLevel
  /** True for the YOLO path, which is the All-in plan with its own heading. */
  isYolo: boolean
  /** Native items the app can act on, such as the hotkey check. Empty outside the Basil app window. */
  nativeHandledIds?: ReadonlySet<string>
  /** Runs the ticked native items after the backend apply succeeds and returns one result for each. It must not throw. */
  nativeApplier?: (ids: readonly string[], context: NativeExpressContext) => Promise<ExpressItemResult[]>
  onSelectModelAccess: (access: SetupAgentModelAccess) => void
  onFinished: () => void
  onChooseManual: () => void
  /** Returns to the first screen, where the user picks how to set up. Offered until the plan is applied. */
  onBackToStart?: () => void
}

/** The whole express flow: read the plan for this Mac, confirm it, apply it, then watch it finish. */
export function ExpressSetup({
  comfort,
  isYolo,
  nativeHandledIds = NO_NATIVE_ITEMS,
  nativeApplier,
  onSelectModelAccess,
  onFinished,
  onChooseManual,
  onBackToStart,
}: Props) {
  const [load, setLoad] = useState<LoadState>({ phase: 'loading' })
  const [isChecking, setIsChecking] = useState(false)
  const [deselected, setDeselected] = useState<ReadonlySet<string>>(new Set())
  const [isApplying, setIsApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applyResult, setApplyResult] = useState<ExpressApplyResult | null>(null)
  const isMountedRef = useRef(true)
  // Hotkey choices are held here, not saved, until Do it. The check only runs inside the Basil app window.
  const hotkeys = useSetupHotkeys({ staged: true })

  useEffect(() => {
    isMountedRef.current = true
    return () => { isMountedRef.current = false }
  }, [])

  const loadPlan = useCallback(async (isRecheck: boolean) => {
    if (isRecheck) setIsChecking(true)
    else setLoad({ phase: 'loading' })
    try {
      const plan = await fetchExpressPlan(comfort)
      if (isMountedRef.current) setLoad({ phase: 'ready', plan })
    } catch (error) {
      if (isMountedRef.current) {
        setLoad({ phase: 'error', message: error instanceof Error ? error.message : "I couldn't check this Mac." })
      }
    } finally {
      if (isMountedRef.current) setIsChecking(false)
    }
  }, [comfort])

  useEffect(() => { void loadPlan(false) }, [loadPlan])

  const toggle = (itemId: string) => {
    setDeselected((previous) => {
      const next = new Set(previous)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  const handleApply = async () => {
    if (load.phase !== 'ready' || isApplying) return
    setIsApplying(true)
    setApplyError(null)
    try {
      // Only ids are sent. The backend rebuilds the plan, so a repeated request after a dropped connection starts nothing twice.
      const ids = selectedItemIds(visibleItems(load.plan, nativeHandledIds), deselected)
      const result = await applyExpressPlan(comfort, ids)
      // Native items run after the backend answers, so a backend failure never leaves a hotkey changed without the rest.
      const nativeIds = ids.filter(id => nativeHandledIds.has(id))
      const nativeResults = nativeApplier && nativeIds.length > 0 ? await nativeApplier(nativeIds, { hotkeyChoices: hotkeys.choices }) : []
      if (isMountedRef.current) setApplyResult({ ...result, results: [...result.results, ...nativeResults] })
    } catch (error) {
      if (isMountedRef.current) {
        setApplyError(error instanceof Error ? error.message : "I couldn't do that. Please try again.")
      }
    } finally {
      if (isMountedRef.current) setIsApplying(false)
    }
  }

  if (applyResult) {
    return (
      <ExpressProgress
        result={applyResult}
        onSelectModelAccess={onSelectModelAccess}
        onFinished={onFinished}
        onChooseManual={onChooseManual}
      />
    )
  }

  if (load.phase === 'loading') {
    return (
      <section className="phase-section express-review">
        <p className="eyebrow">Setup</p>
        <h2>Checking this Mac.</h2>
        <SetupWorkingIndicator className="express-working" label="Reading this Mac's memory and free space." />
        {onBackToStart && (
          <div className="express-actions">
            <button type="button" className="secondary-button" onClick={onBackToStart}>← Back</button>
          </div>
        )}
      </section>
    )
  }

  if (load.phase === 'error') {
    return (
      <section className="phase-section express-review">
        <p className="eyebrow">Setup</p>
        <h2>I couldn't check this Mac.</h2>
        <p className="express-error" role="alert">{load.message}</p>
        <div className="express-actions">
          <button type="button" className="primary-button" onClick={() => { void loadPlan(false) }}>Try again</button>
          <button type="button" className="secondary-button" onClick={onChooseManual}>Set it up step by step instead</button>
          {onBackToStart && <button type="button" className="secondary-button" onClick={onBackToStart}>← Back</button>}
        </div>
      </section>
    )
  }

  return (
    <ExpressReview
      plan={load.plan}
      items={visibleItems(load.plan, nativeHandledIds)}
      deselected={deselected}
      isYolo={isYolo}
      isChecking={isChecking}
      isApplying={isApplying}
      applyError={applyError}
      onToggle={toggle}
      onCheckAgain={() => { void loadPlan(true) }}
      onApply={() => { void handleApply() }}
      onChooseManual={onChooseManual}
      onBackToStart={onBackToStart}
      hotkeys={nativeHandledIds.has(HOTKEYS_ITEM_ID) ? hotkeys : undefined}
    />
  )
}
