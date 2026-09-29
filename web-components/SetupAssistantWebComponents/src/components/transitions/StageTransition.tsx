import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'
import type { SetupStage } from '@/state/setupAssistantStore'

// Stage-keyed cross-fade driven by the frame's own CSS animations. While `stageKey` is stable the latest `children` render straight through. When `stageKey` changes, the prior children stay visible while the frame plays its leave animation. The swap happens on that animation's `animationend`, and the enter animation's `animationend` settles the frame to idle. If no animation is running (reduced motion, or an environment without Web Animations), each phase finishes immediately, so a stage change can never stall. The animation names are the transition's contract with setup-assistant.shared.css.

const STAGE_ENTER_ANIMATION = 'setupEnterRise'
const STAGE_LEAVE_ANIMATION = 'setupLeaveRise'

type StageTransitionStatus = 'entering' | 'leaving' | 'idle'

interface StageTransitionProps {
  stageKey: SetupStage
  children: ReactNode
}

function isRunningAnimation(node: HTMLElement | null, animationName: string): boolean {
  if (!node || typeof node.getAnimations !== 'function') return false
  return node.getAnimations().some(animation => (
    (animation as CSSAnimation).animationName === animationName
    && animation.playState !== 'finished'
  ))
}

export function StageTransition({ stageKey, children }: StageTransitionProps) {
  const frameRef = useRef<HTMLDivElement>(null)
  const latestStageKeyRef = useRef(stageKey)
  latestStageKeyRef.current = stageKey
  const [displayedStageKey, setDisplayedStageKey] = useState(stageKey)
  // The leaving frame keeps the last children rendered for its own stage, not the ones captured when that stage mounted.
  const outgoingChildrenRef = useRef(children)
  if (stageKey === displayedStageKey) outgoingChildrenRef.current = children
  const [status, setStatus] = useState<StageTransitionStatus>(() => (prefersReducedMotion() ? 'idle' : 'entering'))
  const statusRef = useRef(status)
  statusRef.current = status

  const swapToLatestStageRef = useRef(() => {})
  swapToLatestStageRef.current = () => {
    setDisplayedStageKey(latestStageKeyRef.current)
    setStatus(prefersReducedMotion() ? 'idle' : 'entering')
  }

  useLayoutEffect(() => {
    if (stageKey === displayedStageKey) {
      if (status === 'leaving') setStatus('entering')
      return
    }
    if (prefersReducedMotion()) {
      swapToLatestStageRef.current()
      return
    }
    if (status !== 'leaving') setStatus('leaving')
  }, [stageKey, displayedStageKey, status])

  useLayoutEffect(() => {
    if (status === 'idle') return
    const expectedAnimation = status === 'leaving' ? STAGE_LEAVE_ANIMATION : STAGE_ENTER_ANIMATION
    if (isRunningAnimation(frameRef.current, expectedAnimation)) return
    if (status === 'leaving') swapToLatestStageRef.current()
    else setStatus('idle')
  }, [status, displayedStageKey])

  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return undefined
    const handleAnimationEnd = (event: AnimationEvent) => {
      if (event.target !== frame) return
      if (statusRef.current === 'leaving' && event.animationName === STAGE_LEAVE_ANIMATION) {
        swapToLatestStageRef.current()
      } else if (statusRef.current === 'entering' && event.animationName === STAGE_ENTER_ANIMATION) {
        setStatus('idle')
      }
    }
    frame.addEventListener('animationend', handleAnimationEnd)
    return () => frame.removeEventListener('animationend', handleAnimationEnd)
  }, [displayedStageKey])

  const currentChildren = displayedStageKey === stageKey && status !== 'leaving'
    ? children
    : outgoingChildrenRef.current

  return (
    <div ref={frameRef} className={`setup-stage-frame ${status}`} key={displayedStageKey}>
      {currentChildren}
    </div>
  )
}
