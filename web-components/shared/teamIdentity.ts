export interface TeamMemberIdentity {
  displayName: string;
  descriptor: string;
  pairedName: string;
  shortDescription: string;
}

/**
 * Central source for user-facing Basil team member labels across web bundles; mirrors client/Sources/Support/BasilTeamIdentity.swift.
 *
 * Quick Assist (Dill) answers each request, including each refinement, in a single model turn, even when that turn performs research. Agent (Paprika) runs a multi-step loop with tools, progress, and approvals, and can work on many tasks at once. Internal identifiers such as AssistantSession and AgentTask are never user-visible.
 */
export const BASIL_TEAM = {
  assistantSession: {
    displayName: 'Dill',
    descriptor: 'Quick Assist',
    pairedName: 'Dill (Quick Assist)',
    shortDescription: 'Helps you draft, summarize, respond, research, and find the right words in the moment.',
  },
  agentTask: {
    displayName: 'Paprika',
    descriptor: 'Agent',
    pairedName: 'Paprika (Agent)',
    shortDescription: 'Takes a task, works through the steps, and brings back a result.',
  },
} as const satisfies Record<string, TeamMemberIdentity>;
