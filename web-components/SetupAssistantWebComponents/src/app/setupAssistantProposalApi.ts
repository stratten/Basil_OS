import type {
  SetupActionExecutionResponse,
  SetupAppearanceChangeSummary,
  SetupToolApprovalState,
} from '@/types'
import type { FontConfig, ThemeConfig } from '@/theme/themeBootstrap'

import { buildAppearanceChangeSummary } from './appearanceChangeSummary'

// HTTP + response-shape helpers for setup-assistant proposal decisions.
// Lives outside the component so the proposal-action hook can stay focused
// on dispatching state transitions; the network layer and the
// failure-message extraction are mechanical and worth isolating.

declare global {
  interface Window {
    basilSetupAssistantConfig?: {
      apiBaseUrl?: string
      theme?: ThemeConfig
      fonts?: FontConfig
    }
  }
}

export const API_BASE = window.basilSetupAssistantConfig?.apiBaseUrl ?? ''

export async function postProposalDecision(
  proposalId: string,
  approvalState: SetupToolApprovalState,
): Promise<SetupActionExecutionResponse | null> {
  const endpoint =
    approvalState === 'approved' ? 'approve' : approvalState === 'deferred' ? 'defer' : 'decline'
  const response = await fetch(`${API_BASE}/setup-assistant/proposals/${proposalId}/${endpoint}`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error(await readSetupErrorMessage(response))
  }
  if (approvalState !== 'approved') {
    return null
  }
  return await response.json() as SetupActionExecutionResponse
}

async function readSetupErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) {
      return body.detail
    }
  } catch {
    // Fall back to a stable user-facing message below.
  }
  return 'I could not update that setup proposal.'
}

export function summarizeExecutionResponse(response: SetupActionExecutionResponse | null): {
  failed: boolean
  message: string
  appearanceChange: SetupAppearanceChangeSummary | null
} {
  const results = response?.results ?? []
  const failedResult = results.find(result => result.status === 'failed')
  if (failedResult) {
    return {
      failed: true,
      message: failedResult.message || 'The approved action failed.',
      appearanceChange: null,
    }
  }
  const appliedResult = results.find(result => (
    result.status === 'applied' || result.status === 'executed' || result.status === 'skipped'
  ))
  return {
    failed: false,
    message: appliedResult?.message || 'Approved setup action completed.',
    appearanceChange: buildAppearanceChangeSummary(appliedResult),
  }
}
