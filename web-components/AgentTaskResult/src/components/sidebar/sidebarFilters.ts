import {
  countActiveFilters as countActiveConditions,
  endOfLocalDayIso,
  startOfLocalDayIso,
} from '@shared/historyFilters/historyFilterDates';
import type { AgentState } from '../../types';

// The date helpers live in shared/historyFilters; re-exported so existing imports and tests keep working.
export { endOfLocalDayIso, startOfLocalDayIso };

export type SourceFilter = 'any' | 'direct' | 'conversation' | 'todo' | 'meeting' | 'scheduled';
export type StatusFilter = 'any' | 'active' | 'completed' | 'failed' | 'canceled';
export type DocumentsFilter = 'any' | 'yes' | 'no';
export type TurnsFilter = 'any' | 'single' | 'follow_ups';

export interface SidebarFilters {
  /** Local calendar day, "YYYY-MM-DD", or null for no lower bound. */
  startDate: string | null;
  /** Local calendar day, "YYYY-MM-DD", or null for no upper bound. */
  endDate: string | null;
  source: SourceFilter;
  status: StatusFilter;
  app: string;
  documents: DocumentsFilter;
  turns: TurnsFilter;
}

export const EMPTY_SIDEBAR_FILTERS: SidebarFilters = {
  startDate: null,
  endDate: null,
  source: 'any',
  status: 'any',
  app: '',
  documents: 'any',
  turns: 'any',
};

/** The query parameters of the history list and search routes that the filters map onto. */
export interface AgentTaskFilterParams {
  start_date?: string;
  end_date?: string;
  source?: string;
  status?: string;
  app?: string;
  has_documents?: boolean;
  turns?: string;
}

export function countActiveFilters(filters: SidebarFilters): number {
  return countActiveConditions([
    filters.startDate,
    filters.endDate,
    filters.source !== 'any',
    filters.status !== 'any',
    filters.app.trim(),
    filters.documents !== 'any',
    filters.turns !== 'any',
  ]);
}

export function hasActiveFilters(filters: SidebarFilters): boolean {
  return countActiveFilters(filters) > 0;
}

export function toFilterParams(filters: SidebarFilters): AgentTaskFilterParams {
  const params: AgentTaskFilterParams = {};
  const start = filters.startDate ? startOfLocalDayIso(filters.startDate) : undefined;
  const end = filters.endDate ? endOfLocalDayIso(filters.endDate) : undefined;
  if (start) params.start_date = start;
  if (end) params.end_date = end;
  if (filters.source !== 'any') params.source = filters.source;
  if (filters.status !== 'any') params.status = filters.status;
  const app = filters.app.trim();
  if (app) params.app = app;
  if (filters.documents !== 'any') params.has_documents = filters.documents === 'yes';
  if (filters.turns !== 'any') params.turns = filters.turns;
  return params;
}

const NO_BACKEND_MATCHES: ReadonlySet<string> = new Set();
const ACTIVE_LIVE_STATUSES = ['capturing', 'routing', 'processing', 'awaitingInput', 'paused'];

function liveSource(agent: AgentState): Exclude<SourceFilter, 'any'> {
  switch (agent.originType) {
    case 'conversation':
      return 'conversation';
    case 'todo':
    case 'todo_workspace':
      return 'todo';
    case 'meeting':
      return 'meeting';
    case 'scheduled_task':
      return 'scheduled';
    default:
      return 'direct';
  }
}

function liveStatusMatches(agent: AgentState, status: StatusFilter): boolean {
  if (status === 'any') return true;
  if (status === 'canceled') return Boolean(agent.isCanceled);
  if (agent.isCanceled) return false;
  if (status === 'active') return ACTIVE_LIVE_STATUSES.includes(agent.status);
  return agent.status === status;
}

/**
 * Whether a task held live in the window's store passes the filters.
 * The store merges live tasks into the Tasks list on top of the fetched rows, so they need the same narrowing the backend applies to the rest.
 * The store does not know which application a task was captured in, so an application filter keeps a live task only when the backend's filtered rows include its chain (`backendMatchedIds`).
 */
export function liveAgentMatchesFilters(
  agent: AgentState,
  filters: SidebarFilters,
  backendMatchedIds: ReadonlySet<string> = NO_BACKEND_MATCHES,
): boolean {
  if (!hasActiveFilters(filters)) return true;
  if (!liveStatusMatches(agent, filters.status)) return false;
  if (filters.source !== 'any' && liveSource(agent) !== filters.source) return false;
  if (filters.app.trim()) {
    const matchedByBackend = backendMatchedIds.has(agent.agentTaskId)
      || (agent.rootTaskId !== undefined && backendMatchedIds.has(agent.rootTaskId));
    if (!matchedByBackend) return false;
  }
  if (filters.documents !== 'any' && (agent.structuredFiles.length > 0) !== (filters.documents === 'yes')) return false;
  if (filters.turns !== 'any' && (agent.agentTaskHistory.length > 0) !== (filters.turns === 'follow_ups')) return false;
  const moment = Date.parse(agent.timestamp);
  if (Number.isNaN(moment)) return !filters.startDate && !filters.endDate;
  const start = filters.startDate ? startOfLocalDayIso(filters.startDate) : undefined;
  const end = filters.endDate ? endOfLocalDayIso(filters.endDate) : undefined;
  if (start && moment < Date.parse(start)) return false;
  if (end && moment > Date.parse(end)) return false;
  return true;
}
