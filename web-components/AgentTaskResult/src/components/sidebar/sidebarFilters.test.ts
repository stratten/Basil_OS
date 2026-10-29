import { describe, expect, it } from 'vitest';
import type { AgentState } from '../../types';
import {
  EMPTY_SIDEBAR_FILTERS,
  countActiveFilters,
  endOfLocalDayIso,
  hasActiveFilters,
  liveAgentMatchesFilters,
  startOfLocalDayIso,
  toFilterParams,
  type SidebarFilters,
} from './sidebarFilters';

function filters(change: Partial<SidebarFilters>): SidebarFilters {
  return { ...EMPTY_SIDEBAR_FILTERS, ...change };
}

function liveAgent(change: Partial<AgentState> = {}): AgentState {
  return {
    agentTaskId: 'live-1',
    originalPrompt: 'Draft the report',
    status: 'processing',
    structuredFiles: [],
    agentTaskHistory: [],
    timestamp: new Date(2026, 2, 10, 15, 30).toISOString(),
    ...change,
  } as AgentState;
}

describe('sidebarFilters', () => {
  it('counts each active control once and treats the cleared state as inactive', () => {
    expect(countActiveFilters(EMPTY_SIDEBAR_FILTERS)).toBe(0);
    expect(hasActiveFilters(EMPTY_SIDEBAR_FILTERS)).toBe(false);
    expect(countActiveFilters(filters({ startDate: '2026-03-01', endDate: '2026-03-31' }))).toBe(2);
    expect(countActiveFilters(filters({ source: 'meeting', status: 'failed', app: 'Safari', documents: 'no', turns: 'single' }))).toBe(5);
    expect(countActiveFilters(filters({ app: '   ' }))).toBe(0);
  });

  it('sends no parameters for the cleared state', () => {
    expect(toFilterParams(EMPTY_SIDEBAR_FILTERS)).toEqual({});
  });

  it('maps every control to its route parameter', () => {
    expect(toFilterParams(filters({
      startDate: '2026-03-01',
      endDate: '2026-03-31',
      source: 'scheduled',
      status: 'active',
      app: '  Safari ',
      documents: 'yes',
      turns: 'follow_ups',
    }))).toEqual({
      start_date: startOfLocalDayIso('2026-03-01'),
      end_date: endOfLocalDayIso('2026-03-31'),
      source: 'scheduled',
      status: 'active',
      app: 'Safari',
      has_documents: true,
      turns: 'follow_ups',
    });
    expect(toFilterParams(filters({ documents: 'no' })).has_documents).toBe(false);
  });

  it('bounds a local day from its first to its last instant and ignores malformed days', () => {
    const start = Date.parse(startOfLocalDayIso('2026-03-10')!);
    const end = Date.parse(endOfLocalDayIso('2026-03-10')!);
    expect(end - start).toBe(24 * 60 * 60 * 1000 - 1);
    expect(startOfLocalDayIso('March 10')).toBeUndefined();
    expect(toFilterParams(filters({ startDate: 'garbage' }))).toEqual({});
  });

  it('lets every live task through when no filter is active', () => {
    expect(liveAgentMatchesFilters(liveAgent(), EMPTY_SIDEBAR_FILTERS)).toBe(true);
  });

  it('matches the live status filter against running, finished and canceled tasks', () => {
    expect(liveAgentMatchesFilters(liveAgent({ status: 'awaitingInput' }), filters({ status: 'active' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ status: 'completed' }), filters({ status: 'active' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent({ status: 'completed' }), filters({ status: 'completed' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ status: 'failed' }), filters({ status: 'failed' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ status: 'failed', isCanceled: true }), filters({ status: 'failed' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent({ status: 'failed', isCanceled: true }), filters({ status: 'canceled' }))).toBe(true);
  });

  it('maps live origin types onto the source filter', () => {
    expect(liveAgentMatchesFilters(liveAgent(), filters({ source: 'direct' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ originType: 'conversation' }), filters({ source: 'conversation' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ originType: 'todo_workspace' }), filters({ source: 'todo' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ originType: 'scheduled_task' }), filters({ source: 'scheduled' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ originType: 'meeting' }), filters({ source: 'direct' }))).toBe(false);
  });

  it('applies the document, turn and application filters to live tasks', () => {
    expect(liveAgentMatchesFilters(liveAgent(), filters({ documents: 'yes' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ documents: 'no' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ turns: 'follow_ups' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ turns: 'single' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ app: 'Safari' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ app: 'Safari' }), new Set(['live-1']))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent({ rootTaskId: 'root-9' }), filters({ app: 'Safari' }), new Set(['root-9']))).toBe(true);
  });

  it('applies the local-day bounds to the live task timestamp inclusively', () => {
    expect(liveAgentMatchesFilters(liveAgent(), filters({ startDate: '2026-03-10', endDate: '2026-03-10' }))).toBe(true);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ startDate: '2026-03-11' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent(), filters({ endDate: '2026-03-09' }))).toBe(false);
    expect(liveAgentMatchesFilters(liveAgent({ timestamp: 'not a date' }), filters({ startDate: '2026-03-01' }))).toBe(false);
  });
});
