import { useCallback, useEffect, useRef, useState } from 'react'

import { SetupAgendaSidebar } from '@/components/agenda/SetupAgendaSidebar'
import { BasilArtifactPanel } from '@/components/conversation/BasilArtifactPanel'
import { BasilConversation } from '@/components/conversation/BasilConversation'
import { OrientationInterstitial } from '@/components/discovery/OrientationInterstitial'
import { ExpressSetup } from '@/components/express/ExpressSetup'
import { applyNativeExpressItems, nativeHandledItemIds } from '@/components/express/expressNativeHotkeys'
import type { ComfortLevel } from '@/components/express/expressTypes'
import { IntroAndPrivacy } from '@/components/intro/IntroAndPrivacy'
import { WelcomeIntro } from '@/components/intro/WelcomeIntro'
import { LocalModelFailureBanner } from '@/components/layout/LocalModelFailureBanner'
import { SetupShell } from '@/components/layout/SetupShell'
import { SetupStepActions } from '@/components/layout/SetupStepActions'
import { StarterDownloadsStatus } from '@/components/layout/StarterDownloadsStatus'
import { StageTransition } from '@/components/transitions/StageTransition'
import { SetupWrapUpPanel } from '@/components/wrapup/SetupWrapUpPanel'
import { closeSetupAssistant, notifySetupAssistantReady, reportProblem, showDiagnosticLogs } from '@/services/bridge'
import {
  type SetupAgendaConfirmationResolution,
  useSetupAssistantStore,
} from '@/state/setupAssistantStore'
import type { SetupToolApprovalState } from '@/types'

import { useSetupAgentStream } from './hooks/useSetupAgentStream'
import { useSetupCompletion } from './hooks/useSetupCompletion'
import { useSetupDiscovery } from './hooks/useSetupDiscovery'
import { useSetupObservations } from './hooks/useSetupObservations'
import { useSetupProposalActions } from './hooks/useSetupProposalActions'
import {
  EMAIL_METADATA_CONTEXT_PROMPT,
  SETUP_CONVERSATION_START_PROMPT,
} from './setupAssistantPrompts'

// Top-level orchestrator for the setup assistant experience. Owns the
// composition of five behavioral hooks (stream, observations, discovery,
// proposals, completion) plus three small "glue" handlers that wire the
// hooks together for each user-driven moment (intro -> orientation,
// orientation -> conversation, user typed a message). All heavy logic
// lives in the hooks; this file is intentionally thin so the shape of
// the app — which stages exist, which props each stage view takes, when
// the stage transition runs — stays visible at a glance.

export function SetupAssistantApp() {
  const store = useSetupAssistantStore()
  const {
    startStream,
    abort,
    buildRequest,
    isOrientationAgentSettled,
    resetOrientationSettled,
  } = useSetupAgentStream({ store })
  const { handleAgendaConfirmationResolved } = useSetupObservations({ store, startStream })
  const {
    fetchDiscoveryFactsForOrientation,
    collectOptionalEmailMetadataIfUseful,
    isDiscoveryFetching,
  } = useSetupDiscovery({ store })
  const { handleReceiptAction, handleApproveAll } = useSetupProposalActions({ store, startStream })
  const { handleFinish, handleSkip } = useSetupCompletion({ store, buildRequest, abort })
  // True while newly proposed agenda items are animating in; the first Basil message waits for it so the agenda lands before the reply types in.
  const [isAgendaEntering, setIsAgendaEntering] = useState(false)
  // Which of the manual flow's steps opens first. 'model' is where Express hands over when it cannot set up the thinking model itself.
  const [introStartStep, setIntroStartStep] = useState<'downloads' | 'model'>('downloads')
  // YOLO is the All-in plan with its own heading, so the comfort level alone cannot tell the two paths apart.
  const [isYoloPath, setIsYoloPath] = useState(false)
  // Set once the person leaves orientation, so a discovery sweep that finishes later does not start the orientation stream over their conversation.
  const orientationLeftRef = useRef(false)
  const receiptActionRef = useRef(handleReceiptAction)
  const approveAllRef = useRef(handleApproveAll)
  const agendaConfirmationResolutionRef = useRef(handleAgendaConfirmationResolved)
  const setAgendaSidebarCollapsedRef = useRef(store.setAgendaSidebarCollapsed)
  const applyEventRef = useRef(store.applyEvent)
  receiptActionRef.current = handleReceiptAction
  approveAllRef.current = handleApproveAll
  agendaConfirmationResolutionRef.current = handleAgendaConfirmationResolved
  setAgendaSidebarCollapsedRef.current = store.setAgendaSidebarCollapsed
  applyEventRef.current = store.applyEvent

  const invokeReceiptAction = useCallback((proposalId: string, approvalState: SetupToolApprovalState) => {
    receiptActionRef.current(proposalId, approvalState)
  }, [])

  const invokeApproveAll = useCallback((proposalIds: string[]) => {
    approveAllRef.current(proposalIds)
  }, [])

  const invokeAgendaConfirmationResolution = useCallback((
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => {
    agendaConfirmationResolutionRef.current(confirmationId, resolution)
  }, [])

  const toggleAgendaSidebar = useCallback((collapsed: boolean) => {
    setAgendaSidebarCollapsedRef.current(collapsed)
  }, [])

  const closeArtifact = useCallback((artifactId: string) => {
    applyEventRef.current({
      kind: 'artifact_closed',
      payload: { artifact_id: artifactId },
      created_at: new Date().toISOString(),
    })
  }, [])

  useEffect(() => {
    notifySetupAssistantReady()
  }, [])

  const handleIntroContinue = (initialMessage: string, interactionStyle: string[] = []) => {
    store.setInteractionStyle(interactionStyle)
    resetOrientationSettled()
    orientationLeftRef.current = false
    store.setStage('orientation')
    if (initialMessage) {
      store.appendUserMessage(initialMessage)
    }
    void (async () => {
      const facts = await fetchDiscoveryFactsForOrientation()
      // The person may have continued past orientation while the sweep ran. Starting the orientation stream now would cut off their conversation.
      if (orientationLeftRef.current) return
      startStream(initialMessage, facts, 'deterministic_discovery', 'orientation')
    })()
  }

  const openManualSetup = (startStep: 'downloads' | 'model') => {
    setIntroStartStep(startStep)
    store.setStage('intro_and_privacy')
  }

  // The first screen stays reachable after a path is chosen, so someone partway through step by step can still switch to the quick route.
  const backToPathChooser = () => {
    store.setStage('welcome')
  }

  const startExpressSetup = (comfort: ComfortLevel, isYolo = false) => {
    setIsYoloPath(isYolo)
    store.setExpressComfort(comfort)
    store.setStage('express')
  }

  const handleOrientationContinue = () => {
    orientationLeftRef.current = true
    store.setStage('conversation')
    startStream(SETUP_CONVERSATION_START_PROMPT, undefined, 'agent_synthesis', 'conversation')
  }

  // Runs the last thing the user said again, for the failure banner's Try again. Before the user has said anything it re-sends an empty message for the current stage.
  const handleRetryLastTurn = () => {
    const lastUserMessage = [...store.state.messages].reverse().find(message => message.role === 'user')
    store.applyEvent({
      kind: 'turn_started',
      payload: {},
      created_at: new Date().toISOString(),
    })
    startStream(lastUserMessage?.content ?? '')
  }

  const handleUserMessage = (content: string, preliminaryStatusMessage?: string | null) => {
    store.appendUserMessage(content)
    store.setStage('conversation')
    // Optimistically flip the working indicator on in the same frame
    // as the user's bubble. Without this, anything between here and
    // the backend's first SSE byte reads as dead air to the user:
    // for Dill-shaped chips that path includes a multi-second
    // sent-email-metadata pre-flight (collectOptionalEmailMetadataIfUseful)
    // before we even open the agent stream, plus the POST round-trip
    // and the agent's first LLM call before `turn_started` lands and
    // sets isStreaming itself. Synthesizing the same `turn_started`
    // event locally is idempotent — when the real one arrives over
    // SSE it re-applies the same state (no visible change) and the
    // agent's first narrate_progress then upgrades the indicator's
    // label from the generic line to its specific narration.
    store.applyEvent({
      kind: 'turn_started',
      payload: {},
      created_at: new Date().toISOString(),
    })
    if (preliminaryStatusMessage?.trim()) {
      store.applyEvent({
        kind: 'progress_narration',
        payload: { message: preliminaryStatusMessage.trim() },
        created_at: new Date().toISOString(),
      })
    }
    void (async () => {
      const discoveryFacts = await collectOptionalEmailMetadataIfUseful(content)
      startStream(
        discoveryFacts ? `${content}\n\n${EMAIL_METADATA_CONTEXT_PROMPT}` : content,
        discoveryFacts,
        'agent_synthesis',
        'conversation',
        undefined,
        preliminaryStatusMessage,
      )
    })()
  }

  const orientationReady = (
    store.state.setupStage === 'orientation'
    && isOrientationAgentSettled
    && !isDiscoveryFetching
    && !store.state.isStreaming
  )
  const hasActiveArtifact = Boolean(store.state.activeArtifact?.is_open)

  const renderCurrentSetupStage = () => {
    if (store.state.setupStage === 'welcome') {
      return (
        <WelcomeIntro
          onChooseManual={() => openManualSetup('downloads')}
          onChooseSelf={comfort => startExpressSetup(comfort)}
          onChooseYolo={() => startExpressSetup('all_in', true)}
        />
      )
    }

    if (store.state.setupStage === 'express') {
      return (
        <ExpressSetup
          comfort={store.state.expressComfort ?? 'cautious'}
          isYolo={isYoloPath}
          nativeHandledIds={nativeHandledItemIds()}
          nativeApplier={applyNativeExpressItems}
          onSelectModelAccess={store.setModelAccess}
          onFinished={() => handleIntroContinue('')}
          onChooseManual={() => openManualSetup('model')}
          onBackToStart={backToPathChooser}
        />
      )
    }

    if (store.state.setupStage === 'intro_and_privacy') {
      return (
        <IntroAndPrivacy
          selectedModelAccess={store.state.setupAgentModelAccess}
          onSelectModelAccess={store.setModelAccess}
          onContinue={handleIntroContinue}
          initialStep={introStartStep}
          onBackToStart={backToPathChooser}
          onContextImported={store.mergeImportedContext}
          onContextImportUndone={store.clearImportedProfile}
        />
      )
    }

    if (store.state.setupStage === 'orientation') {
      return (
        <OrientationInterstitial
          observations={store.state.observations}
          orientationReady={orientationReady}
          isDiscoveryFetching={isDiscoveryFetching}
          isAgentStreaming={store.state.isStreaming}
          latestProgressNarration={store.state.latestProgressNarration}
          importedContext={store.state.importedContext}
          onReadyForConversation={handleOrientationContinue}
        />
      )
    }

    if (store.state.setupStage === 'conversation') {
      return (
        <>
          <div
            className={
              'setup-workspace'
              + (hasActiveArtifact ? ' with-artifact' : '')
              + (store.state.isAgendaSidebarCollapsed ? ' with-collapsed-agenda' : '')
            }
          >
            <SetupAgendaSidebar
              items={store.state.sessionAgenda}
              isCollapsed={store.state.isAgendaSidebarCollapsed}
              onToggleCollapsed={toggleAgendaSidebar}
              onEntranceChange={setIsAgendaEntering}
            />
            <BasilConversation
              messages={store.state.messages}
              chips={store.state.currentChips}
              chipsMultiSelect={store.state.currentChipsMultiSelect}
              observations={store.state.observations}
              pendingProposals={store.state.pendingProposals}
              isStreaming={store.state.isStreaming}
              workingPrimaryLabel={store.state.latestProgressNarration?.message ?? null}
              workingActivityLabel={store.state.lastStreamActivity?.label ?? null}
              trackedAgentTasks={store.state.trackedAgentTasks}
              trackedAssistantSessions={store.state.trackedAssistantSessions}
              holdMessageReveal={isAgendaEntering}
              onUserMessage={handleUserMessage}
              onReceiptAction={invokeReceiptAction}
              onApproveAll={invokeApproveAll}
              onAgendaConfirmationResolved={invokeAgendaConfirmationResolution}
            />
            <BasilArtifactPanel
              artifact={store.state.activeArtifact}
              pendingProposals={store.state.pendingProposals}
              onClose={closeArtifact}
              onReceiptAction={invokeReceiptAction}
            />
          </div>
          <SetupStepActions>
            <button type="button" className="secondary-button setup-done-button" onClick={handleFinish}>
              Done with setup
            </button>
          </SetupStepActions>
        </>
      )
    }

    return (
      <>
        <SetupWrapUpPanel
          wasSkipped={store.state.wasSkipped}
          wrapUpProposal={store.state.wrapUpProposal}
          isFinalizingWrapUp={store.state.isFinalizingWrapUp}
          finalizeError={store.state.finalizeError}
        />
        <SetupStepActions>
          <button type="button" className="primary-button setup-close-button" onClick={closeSetupAssistant}>
            Close
          </button>
        </SetupStepActions>
      </>
    )
  }

  return (
    <SetupShell
      setupStage={store.state.setupStage}
      hasActiveArtifact={hasActiveArtifact}
      onSkip={handleSkip}
    >
      {store.state.localModelFailure ? (
        <LocalModelFailureBanner
          failure={store.state.localModelFailure}
          onRetry={handleRetryLastTurn}
          onChooseAnotherRoute={() => openManualSetup('downloads')}
          onReport={detail => reportProblem('setup_assistant', detail)}
          onShowLogs={detail => showDiagnosticLogs('setup_assistant', detail)}
        />
      ) : (
        store.state.errorMessage && <div className="error-banner">{store.state.errorMessage}</div>
      )}

      {/* The first screen has its own Model downloads step, so this status panel appears only on the wrap-up screen. */}
      {store.state.setupStage === 'wrap_up' && <StarterDownloadsStatus />}

      <StageTransition stageKey={store.state.setupStage}>
        {renderCurrentSetupStage()}
      </StageTransition>
    </SetupShell>
  )
}
