export interface TeamMemberIdentity {
  displayName: string;
  roleLabel: string;
  shortDescription: string;
}

/**
 * Central source for user-facing Basil team member labels in onboarding.
 *
 * Durable source concepts should use capability names such as
 * assistant-session and agent-task. Character names like "Dill" and
 * "Paprika" belong here so pilot-feedback changes stay localized to this
 * catalog instead of spreading through component copy and route names.
 */
export const BASIL_TEAM = {
  assistantSession: {
    displayName: 'Dill',
    roleLabel: 'Writing partner',
    shortDescription: 'Helps you draft, summarize, respond, research, and find the right words in the moment.',
  },
  agentTask: {
    displayName: 'Paprika',
    roleLabel: 'Task runner',
    shortDescription: 'Takes a task, works through the steps, and brings back a result.',
  },
  controlBoard: {
    displayName: 'Saffron',
    roleLabel: 'Control board agent',
    shortDescription: 'Watches approved sources, coordinates follow-up work, and brings back summaries, drafts, and options for review.',
  },
} as const satisfies Record<string, TeamMemberIdentity>;
