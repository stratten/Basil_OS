import { useEffect, useRef, useState } from 'react'

import {
  type SetupAgentStreamController,
  streamSetupAgentEvents,
} from '@/services/eventStream'
import type {
  SetupStage,
  useSetupAssistantStore,
} from '@/state/setupAssistantStore'
import type { SetupAgentRequest, SetupDiscoveryFact } from '@/types'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>

// Foundation hook for the setup-assistant orchestration: owns the SSE
// controller ref, the request builder, the orientation-settled flag, and
// the unmount-time abort cleanup. Every other behavioral hook in
// app/hooks/ consumes `startStream` (and sometimes `buildRequest` /
// `abort`) from here, so this hook is the single source of truth for the
// stream lifecycle. Returns a stable-shaped imperative API rather than
// state, so callers can fire-and-forget; only `isOrientationAgentSettled`
// triggers a re-render when it flips.

export interface SetupAgentStreamApi {
  startStream: (
    latestMessage: string,
    discoveryFactsOverride?: SetupDiscoveryFact[],
    phaseOverride?: SetupAgentRequest['phase'],
    setupStageOverride?: SetupStage,
    executionOutcomesOverride?: SetupAgentRequest['execution_outcomes'],
    initialProgressMessage?: string | null,
  ) => void
  abort: () => void
  buildRequest: (
    latestMessage: string,
    discoveryFactsOverride?: SetupDiscoveryFact[],
    phaseOverride?: SetupAgentRequest['phase'],
    setupStageOverride?: SetupStage,
    executionOutcomesOverride?: SetupAgentRequest['execution_outcomes'],
  ) => SetupAgentRequest
  isOrientationAgentSettled: boolean
  resetOrientationSettled: () => void
}

export function useSetupAgentStream({
  store,
}: {
  store: SetupAssistantStore
}): SetupAgentStreamApi {
  const streamControllerRef = useRef<SetupAgentStreamController | null>(null)
  const [isOrientationAgentSettled, setIsOrientationAgentSettled] = useState(false)

  useEffect(() => () => streamControllerRef.current?.abort(), [])

  const buildRequest: SetupAgentStreamApi['buildRequest'] = (
    latestMessage,
    discoveryFactsOverride,
    phaseOverride,
    setupStageOverride,
    executionOutcomesOverride,
  ) => {
    const setupAgentModelAccess = store.state.setupAgentModelAccess
    if (!setupAgentModelAccess?.resolved) {
      throw new Error('Setup agent model access has not been confirmed yet.')
    }

    return {
    latest_message: latestMessage,
    phase: phaseOverride ?? (store.state.setupStage === 'orientation' ? 'deterministic_discovery' : 'agent_synthesis'),
    technical_depth: 'practical',
    interview_answers: [],
    discovery_facts: discoveryFactsOverride ?? store.state.discoveryFacts,
    // Filter user-action acknowledgment chips out of the agent's
    // chat_history. The chips are a UI receipt that the user resolved
    // an inline consent proposal (Approve / Not now / Suggest
    // something else), not a typed utterance. The agent already
    // learns what happened via execution_outcomes (terminal
    // observation payloads) and via pendingProposals.approval_state
    // on the receipt itself; feeding it a synthetic "Approved." user
    // turn would either fight or duplicate that signal — worst case
    // the agent narrates the chip copy back at the user as if they
    // actually said it.
    chat_history: store.state.messages
      .filter(message => message.inlineAcknowledgment === undefined)
      .map(message => ({
        id: message.id,
        role: message.role,
        content: message.content || ' ',
        created_at: message.createdAt,
      })),
    existing_recommendations: [],
    existing_profile_suggestions: [],
    existing_writing_sample_candidates: [],
    existing_model_choices: [],
    existing_task_offers: [],
    approved_tool_calls: [],
    setup_agent_model_access: setupAgentModelAccess,
    calibration_events: [],
    current_step_context: {
      setup_stage: setupStageOverride ?? store.state.setupStage,
      observations: store.state.observations,
      active_artifact_id: store.state.activeArtifact?.id,
    },
    setup_agent_model_override_id: null,
    // Round-trip the current agenda back to the backend on every turn so
    // the agent always sees its own session state (status pills, what's
    // pending vs. completed, what the user has skipped). Backend
    // re-shapes the field name from camelCase to snake_case via the
    // SetupSessionAgendaItem pydantic model, but the dict shape goes
    // through untouched — the route's `session_goals` field is typed as
    // List[Dict[str, Any]] specifically so the frontend can pass arbitrary
    // structured state without locking the wire format to a single
    // schema. The seeded catalog only fires when this list is empty
    // (first conversation-phase turn); see _resolve_agenda_items_for_turn
    // in setup_agent_runtime.py.
    session_goals: store.state.sessionAgenda.map(item => ({
      id: item.id,
      title: item.title,
      intent: item.intent,
      kind: item.kind,
      source: item.source,
      status: item.status,
      completion_basis: item.completionBasis ?? null,
    })),
    agenda_items: [],
    execution_outcomes: executionOutcomesOverride ?? [],
    }
  }

  const startStream: SetupAgentStreamApi['startStream'] = (
    latestMessage,
    discoveryFactsOverride,
    phaseOverride,
    setupStageOverride,
    executionOutcomesOverride,
    initialProgressMessage,
  ) => {
    streamControllerRef.current?.abort()
    // Optimistically flip the working indicator on so the window
    // between this call and the backend's first SSE byte (POST
    // round-trip + agent warm-up + first LLM call, typically 2–4s)
    // doesn't read as dead air to the user. Covers every startStream
    // caller — observation-driven re-engagement turns (Paprika
    // terminal, Dill terminal, agenda confirmation resolved) plus
    // the orientation -> conversation transition. handleUserMessage
    // additionally fires its own earlier turn_started before its
    // email-metadata pre-flight; this dispatch is a no-op when that
    // path arrives here, and the real turn_started arriving later
    // over SSE is itself a no-op against this state.
    store.applyEvent({
      kind: 'turn_started',
      payload: {},
      created_at: new Date().toISOString(),
    })
    if (initialProgressMessage?.trim()) {
      store.applyEvent({
        kind: 'progress_narration',
        payload: { message: initialProgressMessage.trim() },
        created_at: new Date().toISOString(),
      })
    }
    streamControllerRef.current = streamSetupAgentEvents(
      buildRequest(
        latestMessage || 'Start setup. Get oriented and help me configure Basil smoothly.',
        discoveryFactsOverride,
        phaseOverride,
        setupStageOverride,
        executionOutcomesOverride,
      ),
      event => {
        if (
          phaseOverride === 'deterministic_discovery'
          && (event.kind === 'turn_complete' || event.kind === 'error')
        ) {
          setIsOrientationAgentSettled(true)
        }
        store.applyEvent(event)
      },
      error => {
        if (phaseOverride === 'deterministic_discovery') {
          setIsOrientationAgentSettled(true)
        }
        store.setError(error.message)
      },
    )
  }

  const abort = () => streamControllerRef.current?.abort()
  const resetOrientationSettled = () => setIsOrientationAgentSettled(false)

  return { startStream, abort, buildRequest, isOrientationAgentSettled, resetOrientationSettled }
}
