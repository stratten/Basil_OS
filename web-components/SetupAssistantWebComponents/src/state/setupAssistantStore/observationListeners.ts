import { useEffect, useRef } from 'react'

import {
  onAgentTaskObservation,
  onAssistantSessionObservation,
  type SetupAgentTaskObservation,
  type SetupAssistantSessionObservation,
} from '@/services/bridge'

import type {
  SetupAgentTaskObservationTurnRequest,
  SetupAssistantSessionObservationTurnRequest,
} from './types'

const BOILERPLATE_PROGRESS_REGEX = /^Agent planning step \d+\.{3}\s*$/
const PROGRESS_DEDUP_FLOOR_MS = 10_000

/**
 * Listen for native agent-task observations emitted by the Swift poller and
 * surface them to the caller for re-engaging the setup agent. Same-content
 * progress observations are deduped within a 10 second floor and obvious
 * AgentExecutor boilerplate ("Agent planning step N...") is dropped before
 * reaching the caller; terminal observations always pass through.
 */
export function useAgentTaskObservationListener(
  onObservationTurnRequested: (request: SetupAgentTaskObservationTurnRequest) => void,
): void {
  const handlerRef = useRef(onObservationTurnRequested)
  handlerRef.current = onObservationTurnRequested

  useEffect(() => {
    const lastSent = new Map<string, { signature: string; at: number }>()

    return onAgentTaskObservation((observation: SetupAgentTaskObservation) => {
      const { agentTaskId, kind, status } = observation
      const currentStep = observation.currentStep?.trim() ?? ''
      const resultMessage = observation.resultMessage?.trim() ?? ''
      const errorMessage = observation.errorMessage?.trim() ?? ''

      if (kind === 'progress' && currentStep && BOILERPLATE_PROGRESS_REGEX.test(currentStep)) {
        return
      }

      const signature = `${status}|${currentStep}|${resultMessage}|${errorMessage}`
      const prior = lastSent.get(agentTaskId)
      const now = Date.now()

      if (
        kind === 'progress' &&
        prior &&
        prior.signature === signature &&
        now - prior.at < PROGRESS_DEDUP_FLOOR_MS
      ) {
        return
      }

      lastSent.set(agentTaskId, { signature, at: now })

      handlerRef.current({
        agentTaskId,
        outcome: {
          agent_task_id: agentTaskId,
          kind: kind === 'terminal' ? 'agent_task_terminal' : 'agent_task_progress',
          status,
          current_step: currentStep || undefined,
          result_message: resultMessage || undefined,
          error_message: errorMessage || undefined,
        },
        isTerminal: kind === 'terminal',
      })

      if (kind === 'terminal') {
        lastSent.delete(agentTaskId)
      }
    })
  }, [])
}

/**
 * Listen for native Dill-assistant-session observations emitted by the
 * AssistantSessionWindowController's Combine seam and surface them to the
 * caller for re-engaging the setup agent. Today setup-launched Dill only
 * emits a single terminal observation per session (no progress events —
 * see the bridge file's rationale), so this hook is simpler than its
 * agent-task counterpart: no boilerplate filter, no progress dedup.
 * Terminal observations always pass through.
 */
export function useAssistantSessionObservationListener(
  onObservationTurnRequested: (request: SetupAssistantSessionObservationTurnRequest) => void,
): void {
  const handlerRef = useRef(onObservationTurnRequested)
  handlerRef.current = onObservationTurnRequested

  useEffect(() => {
    return onAssistantSessionObservation((observation: SetupAssistantSessionObservation) => {
      const { assistantSessionId, kind, status } = observation
      const resultText = observation.resultText?.trim() ?? ''
      const errorMessage = observation.errorMessage?.trim() ?? ''

      handlerRef.current({
        assistantSessionId,
        outcome: {
          assistant_session_id: assistantSessionId,
          kind: 'assistant_session_terminal',
          status,
          result_text: resultText || undefined,
          error_message: errorMessage || undefined,
        },
        isTerminal: kind === 'terminal',
      })
    })
  }, [])
}
