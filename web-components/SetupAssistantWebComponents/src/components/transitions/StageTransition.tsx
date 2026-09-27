import { type ReactNode, useEffect, useRef, useState } from 'react'

import type { SetupStage } from '@/state/setupAssistantStore'

// Stage-keyed cross-fade. While `stageKey` is stable, the latest
// `children` render straight through and `status` settles to 'idle'
// after a short enter window. When `stageKey` changes we hold the prior
// children visible while `status` is 'leaving', then swap to the new
// children once the leave animation finishes and run the enter window
// again. `prefers-reduced-motion: reduce` short-circuits both animation
// phases so the swap is instantaneous for users who request it. The
// timing constants live here (not in the parent) because they're the
// transition's contract, not the app's.

const STAGE_LEAVE_MS = 300
const STAGE_ENTER_MS = 300

type StageTransitionStatus = 'entering' | 'leaving' | 'idle'

interface StageTransitionProps {
  stageKey: SetupStage
  children: ReactNode
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function StageTransition({ stageKey, children }: StageTransitionProps) {
  const latestChildrenRef = useRef(children)
  latestChildrenRef.current = children
  const [displayedStageKey, setDisplayedStageKey] = useState(stageKey)
  const [displayedChildren, setDisplayedChildren] = useState(children)
  const [status, setStatus] = useState<StageTransitionStatus>('entering')

  useEffect(() => {
    if (stageKey === displayedStageKey) {
      if (prefersReducedMotion()) {
        setStatus('idle')
        return undefined
      }
      const enterTimer = window.setTimeout(() => setStatus('idle'), STAGE_ENTER_MS)
      return () => window.clearTimeout(enterTimer)
    }

    if (prefersReducedMotion()) {
      setDisplayedStageKey(stageKey)
      setDisplayedChildren(latestChildrenRef.current)
      setStatus('idle')
      return undefined
    }

    let enterTimer: number | undefined
    setStatus('leaving')
    const leaveTimer = window.setTimeout(() => {
      setDisplayedStageKey(stageKey)
      setDisplayedChildren(latestChildrenRef.current)
      setStatus('entering')
      enterTimer = window.setTimeout(() => setStatus('idle'), STAGE_ENTER_MS)
    }, STAGE_LEAVE_MS)

    return () => {
      window.clearTimeout(leaveTimer)
      if (enterTimer !== undefined) {
        window.clearTimeout(enterTimer)
      }
    }
  }, [displayedStageKey, stageKey])

  const currentChildren = displayedStageKey === stageKey && status !== 'leaving'
    ? children
    : displayedChildren

  return (
    <div className={`setup-stage-frame ${status}`} key={displayedStageKey}>
      {currentChildren}
    </div>
  )
}
