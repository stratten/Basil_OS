import {
  completeSetupAssistant,
  finalizeSetupAssistant,
  skipSetupAssistant,
} from '@/services/api'
import type { useSetupAssistantStore } from '@/state/setupAssistantStore'
import type { SetupWrapUpProposal } from '@/types'

import { buildCompletionPayload, executedReceiptTitles } from '../resume/progressPayload'
import { afterProgressSave } from '../resume/progressSaveGate'
import { buildSavedSessionFields } from '../resume/savedSession'
import { SETUP_FINALIZE_PROMPT } from '../setupAssistantPrompts'
import type { SetupAgentStreamApi } from './useSetupAgentStream'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>

// Owns the three terminal-stage handlers: Done, Skip, and the background finalize call that produces the wrap-up recap. Done and Skip both abort any in-flight stream first (we don't want stale events landing after the user has decided to wrap up), then post the completion payload to the backend so other parts of the app can react. Done is only offered during the conversation stage and ignores calls from any other stage. The background finalize runs only on the Done path, only if the agent has not already proposed a recap mid-conversation (`store.state.wrapUpProposal`), and only once a setup step actually landed; otherwise the wrap-up panel shows its no-steps variant without a model call.

export interface SetupCompletionApi {
  handleFinish: () => void
  handleSkip: () => void
}

export function useSetupCompletion({
  store,
  buildRequest,
  abort,
}: {
  store: SetupAssistantStore
  buildRequest: SetupAgentStreamApi['buildRequest']
  abort: SetupAgentStreamApi['abort']
}): SetupCompletionApi {
  const collectCompletionPayload = (): Parameters<typeof completeSetupAssistant>[0] => buildCompletionPayload(store.state)

  const runFinalizeWrapUpInBackground = () => {
    store.setIsFinalizingWrapUp(true)
    store.setFinalizeError(null)
    void (async () => {
      try {
        const request = buildRequest(SETUP_FINALIZE_PROMPT)
        const proposal = await finalizeSetupAssistant(request)
        if (proposal && typeof proposal.recap === 'string' && proposal.recap.trim().length > 0) {
          store.setWrapUpProposal(proposal as SetupWrapUpProposal)
        } else {
          store.setFinalizeError('I could not put together a personalized recap right now.')
        }
      } catch (error) {
        store.setFinalizeError(error instanceof Error ? error.message : String(error))
      } finally {
        store.setIsFinalizingWrapUp(false)
      }
    })()
  }

  const hasConcreteSetupProgress = (): boolean => (
    store.state.sessionAgenda.some(item => item.status === 'completed')
    || Object.values(store.state.pendingProposals)
      .some(proposal => proposal.approvalState === 'executed' || proposal.approvalState === 'approved')
  )

  const handleFinish = () => {
    if (store.state.setupStage !== 'conversation') return
    abort()
    const shouldFinalizeRecap = !store.state.wrapUpProposal && hasConcreteSetupProgress()
    const payload = collectCompletionPayload()
    store.setStage('wrap_up')
    afterProgressSave(() => {
      completeSetupAssistant(payload)
        .catch(error => store.setError(error instanceof Error ? error.message : String(error)))
    })
    if (shouldFinalizeRecap) {
      runFinalizeWrapUpInBackground()
    }
  }

  const handleSkip = () => {
    abort()
    store.markSetupSkipped()
    // Read before the skip flips the stage to wrap-up, so the saved session records where the person actually was.
    const savedSession = buildSavedSessionFields(store.state, executedReceiptTitles(store.state))
    const skipPayload = { ...collectCompletionPayload(), ...savedSession }
    afterProgressSave(() => {
      skipSetupAssistant(skipPayload)
        .catch(error => store.setError(error instanceof Error ? error.message : String(error)))
    })
  }

  return { handleFinish, handleSkip }
}
