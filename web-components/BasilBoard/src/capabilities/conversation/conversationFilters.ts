import {
  countActiveFilters as countActiveConditions,
  endOfLocalDayIso,
  startOfLocalDayIso,
} from '@shared/historyFilters/historyFilterDates';

export type AgentWorkFilter = 'any' | 'none' | 'has' | 'active' | 'failed';
export type LengthFilter = 'any' | 'single' | 'multi';

export interface ConversationFilters {
  /** Local calendar day, "YYYY-MM-DD", or null for no lower bound. */
  startDate: string | null;
  /** Local calendar day, "YYYY-MM-DD", or null for no upper bound. */
  endDate: string | null;
  agentWork: AgentWorkFilter;
  length: LengthFilter;
}

export const EMPTY_CONVERSATION_FILTERS: ConversationFilters = {
  startDate: null,
  endDate: null,
  agentWork: 'any',
  length: 'any',
};

/** The query parameters of `/conversation/page` that the filters map onto. */
export interface ConversationFilterParams {
  start_date?: string;
  end_date?: string;
  agent_work?: 'none' | 'any' | 'active' | 'failed';
  length?: 'single' | 'multi';
}

export function countActiveConversationFilters(filters: ConversationFilters): number {
  return countActiveConditions([
    filters.startDate,
    filters.endDate,
    filters.agentWork !== 'any',
    filters.length !== 'any',
  ]);
}

export function hasActiveConversationFilters(filters: ConversationFilters): boolean {
  return countActiveConversationFilters(filters) > 0;
}

export function toConversationFilterParams(filters: ConversationFilters): ConversationFilterParams {
  const params: ConversationFilterParams = {};
  const start = filters.startDate ? startOfLocalDayIso(filters.startDate) : undefined;
  const end = filters.endDate ? endOfLocalDayIso(filters.endDate) : undefined;
  if (start) params.start_date = start;
  if (end) params.end_date = end;
  // The panel says "has" for any agent work; the wire value for that is "any", so "any" can mean "no filter" in the UI.
  if (filters.agentWork !== 'any') params.agent_work = filters.agentWork === 'has' ? 'any' : filters.agentWork;
  if (filters.length !== 'any') params.length = filters.length;
  return params;
}
