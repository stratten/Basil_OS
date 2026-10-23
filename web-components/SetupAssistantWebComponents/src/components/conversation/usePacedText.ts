import { useEffect, useRef, useState } from 'react'

import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'

const BASE_CHARS_PER_SECOND = 90
const CATCH_UP_SECONDS = 1.2
const MAX_FRAME_SECONDS = 0.1

// Message ids whose reveal already finished, so a remounted row never replays text the user has read.
const completedRevealIds = new Set<string>()

export function nextRevealBoundary(text: string, index: number): number {
  if (index >= text.length) return text.length
  const match = /\s/.exec(text.slice(index))
  return match ? index + match.index : text.length
}

interface PacedTextOptions {
  messageId: string
  content: string
  progressive: boolean
  streaming: boolean
  hold: boolean
}

export function usePacedText({ messageId, content, progressive, streaming, hold }: PacedTextOptions): string {
  const [skipPacing] = useState(() => (
    !progressive || completedRevealIds.has(messageId) || prefersReducedMotion()
  ))
  const [visibleLength, setVisibleLength] = useState(0)
  const revealedRef = useRef(0)
  const contentRef = useRef(content)
  contentRef.current = content
  const streamingRef = useRef(streaming)
  streamingRef.current = streaming

  useEffect(() => {
    if (skipPacing) return undefined
    const markCompleteIfDone = () => {
      if (!streamingRef.current && revealedRef.current >= contentRef.current.length) {
        completedRevealIds.add(messageId)
      }
    }
    if (hold && revealedRef.current === 0) return undefined
    if (revealedRef.current >= content.length) {
      markCompleteIfDone()
      return undefined
    }
    if (typeof requestAnimationFrame !== 'function') {
      revealedRef.current = content.length
      setVisibleLength(content.length)
      markCompleteIfDone()
      return undefined
    }

    let frameId = 0
    let lastTimestamp: number | null = null
    const step = (timestamp: number) => {
      const elapsedSeconds = lastTimestamp === null
        ? 1 / 60
        : Math.min(MAX_FRAME_SECONDS, (timestamp - lastTimestamp) / 1000)
      lastTimestamp = timestamp
      const target = contentRef.current.length
      const backlog = target - revealedRef.current
      const charsPerSecond = Math.max(BASE_CHARS_PER_SECOND, backlog / CATCH_UP_SECONDS)
      revealedRef.current = Math.min(target, revealedRef.current + charsPerSecond * elapsedSeconds)
      setVisibleLength(nextRevealBoundary(contentRef.current, Math.floor(revealedRef.current)))
      if (revealedRef.current < target) {
        frameId = requestAnimationFrame(step)
      } else {
        markCompleteIfDone()
      }
    }
    frameId = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frameId)
  }, [content, hold, messageId, skipPacing, streaming])

  if (skipPacing) return content
  return content.slice(0, visibleLength)
}
