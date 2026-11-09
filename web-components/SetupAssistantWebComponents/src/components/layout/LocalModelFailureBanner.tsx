import { useCallback, useEffect, useRef, useState } from 'react'

import { type SmallerReasoningModelResult, switchToSmallerReasoningModel } from '@/services/api'
import type { SetupLocalModelFailure, SetupLocalModelFailureActionId } from '@/state/setupAssistantStore'

const SMALLER_MODEL_POLL_MS = 3000

export interface LocalModelFailureBannerProps {
  failure: SetupLocalModelFailure
  /** Runs the last turn again. Also called automatically once a smaller model has been switched to. */
  onRetry: () => void
  /** Returns to the step where the user picks Basil Cloud or their own API key. */
  onChooseAnotherRoute: () => void
  /** Opens the Report a problem flow with the native return code as its only detail. */
  onReport: (detail: string) => void
  /** Saves a redacted diagnostics bundle and shows it in Finder, with the native return code as its only detail. */
  onShowLogs: (detail: string) => void
}

type SmallerModelState =
  | { phase: 'idle' }
  | { phase: 'working'; message: string }
  | { phase: 'failed'; message: string }

/**
 * Shown when a local model could not run on this Mac. It replaces the generic error banner so the user
 * sees a plain-language reason and a way forward instead of a native error string.
 */
export function LocalModelFailureBanner({ failure, onRetry, onChooseAnotherRoute, onReport, onShowLogs }: LocalModelFailureBannerProps) {
  const [smallerModel, setSmallerModel] = useState<SmallerModelState>({ phase: 'idle' })
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)
  const onRetryRef = useRef(onRetry)
  onRetryRef.current = onRetry

  useEffect(() => () => {
    isMountedRef.current = false
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
  }, [])

  const requestSmallerModel = useCallback(async () => {
    let result: SmallerReasoningModelResult
    try {
      result = await switchToSmallerReasoningModel()
    } catch (error) {
      if (!isMountedRef.current) return
      setSmallerModel({
        phase: 'failed',
        message: error instanceof Error ? error.message : 'Basil could not switch models. Please try again.',
      })
      return
    }
    if (!isMountedRef.current) return
    if (result.status === 'switched') {
      setSmallerModel({ phase: 'idle' })
      onRetryRef.current()
      return
    }
    if (result.status === 'downloading') {
      setSmallerModel({ phase: 'working', message: result.message })
      pollTimerRef.current = setTimeout(() => { void requestSmallerModel() }, SMALLER_MODEL_POLL_MS)
      return
    }
    setSmallerModel({ phase: 'failed', message: result.message })
  }, [])

  const handleAction = (actionId: SetupLocalModelFailureActionId) => {
    switch (actionId) {
      case 'retry':
        onRetry()
        return
      case 'smaller_model':
        if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
        setSmallerModel({ phase: 'working', message: 'Checking for a smaller model.' })
        void requestSmallerModel()
        return
      case 'cloud_or_key':
        onChooseAnotherRoute()
        return
      case 'show_logs':
        onShowLogs(failure.detail)
        return
      case 'report':
        onReport(failure.detail)
        return
    }
  }

  const isWorking = smallerModel.phase === 'working'

  return (
    <div className="local-model-failure-banner" role="alert">
      <p className="local-model-failure-banner__message">{failure.message}</p>
      {smallerModel.phase !== 'idle' && (
        <p
          className={`local-model-failure-banner__status${smallerModel.phase === 'failed' ? ' local-model-failure-banner__status--failed' : ''}`}
          role="status"
        >
          {smallerModel.message}
        </p>
      )}
      <div className="local-model-failure-banner__actions">
        {failure.actions.map((action, index) => (
          <button
            key={action.id}
            type="button"
            className={index === 0 ? 'primary-button' : 'secondary-button'}
            disabled={isWorking && action.id === 'smaller_model'}
            onClick={() => handleAction(action.id)}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  )
}
