import { useEffect, useRef, useState } from 'react'

/**
 * Run a callback once a tracked bridge request has resolved.
 *
 * The parent tracks one request at a time through `pendingId`. Call the returned function in the same event handler that tracks the request: the callback runs after `pendingId` stops being that request's id, which lets one action wait for a previous one without a timer.
 */
export function useAfterRequest(pendingId: string | null): (requestId: string, callback: () => void) => void {
  const [awaitedId, setAwaitedId] = useState<string | null>(null)
  const callbackRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!awaitedId || pendingId === awaitedId) return
    const callback = callbackRef.current
    callbackRef.current = null
    setAwaitedId(null)
    callback?.()
  }, [pendingId, awaitedId])

  return (requestId, callback) => {
    callbackRef.current = callback
    setAwaitedId(requestId)
  }
}
