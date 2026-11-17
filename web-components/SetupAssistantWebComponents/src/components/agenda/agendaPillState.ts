import type { SetupSessionAgendaItem } from '@/state/setupAssistantStore'

// The label an agenda item shows. The agent marks one item "in progress", but whether the agent is actually busy on it is a separate fact: it comes from the live turn. Keeping them apart is what lets the list say "Working now" only while something is really happening, and "Your turn" while the agent is waiting for the person.
export type AgendaPillState = 'working' | 'your_turn' | 'pending' | 'completed' | 'skipped' | 'deferred'

export const PILL_LABELS: Record<AgendaPillState, string> = {
  working: 'Working now',
  your_turn: 'Your turn',
  pending: 'To do',
  completed: 'Done',
  skipped: 'Skipped',
  deferred: 'Later',
}

export function agendaPillState(item: SetupSessionAgendaItem, isAgentWorking: boolean): AgendaPillState {
  if (item.status === 'in_progress') return isAgentWorking ? 'working' : 'your_turn'
  return item.status
}

// Items the person can ask for next. The one already in progress and the finished ones are not offered again.
export function isAgendaItemSelectable(item: SetupSessionAgendaItem): boolean {
  return item.status === 'pending' || item.status === 'deferred' || item.status === 'skipped'
}

export function agendaSelectionMessage(item: SetupSessionAgendaItem): string {
  return `Let's do "${item.title}" next.`
}
