import { describe, expect, it } from 'vitest';
import type { BasilBoardTab } from '../contracts';
import { resolveTabDetachBehavior, resolveTabRenderer } from './TabRegistry';

function buildTab(overrides: Partial<BasilBoardTab>): BasilBoardTab {
  return {
    id: 'tab-1',
    title: 'Tab',
    position: 0,
    tab_kind: 'capability',
    status: 'active',
    configuration: {},
    ...overrides,
  };
}

describe('TabRegistry', () => {
  it('resolves the Home renderer by tab_kind', () => {
    const tab = buildTab({ id: 'home', tab_kind: 'home' });
    expect(resolveTabRenderer(tab)).not.toBeNull();
  });

  it('resolves capability renderers by configuration.capability_id', () => {
    const chats = buildTab({ id: 'chats', configuration: { capability_id: 'conversations.history' } });
    const meetings = buildTab({ id: 'meetings', configuration: { capability_id: 'meetings.history' } });
    const todos = buildTab({ id: 'todos', configuration: { capability_id: 'todos.workspace' } });
    expect(resolveTabRenderer(chats)).not.toBeNull();
    expect(resolveTabRenderer(meetings)).not.toBeNull();
    expect(resolveTabRenderer(todos)).not.toBeNull();
  });

  it('returns null for a capability tab with an unknown capability_id', () => {
    const tab = buildTab({ id: 'mystery', configuration: { capability_id: 'unknown.capability' } });
    expect(resolveTabRenderer(tab)).toBeNull();
  });

  it('returns null for an unsupported tab_kind', () => {
    const tab = buildTab({ id: 'bad', tab_kind: 'not_a_real_kind' as BasilBoardTab['tab_kind'] });
    expect(resolveTabRenderer(tab)).toBeNull();
  });

  it('resolves each configured detach strategy and fails closed', () => {
    expect(resolveTabDetachBehavior(buildTab({
      id: 'chats',
      configuration: { capability_id: 'conversations.history', detach_behavior: 'useBoardWindow' },
    }))).toBe('useBoardWindow');
    expect(resolveTabDetachBehavior(buildTab({
      id: 'agent_tasks',
      configuration: { capability_id: 'agent_tasks.history', detach_behavior: 'useNativeWindow' },
    }))).toBe('useNativeWindow');
    expect(resolveTabDetachBehavior(buildTab({ id: 'home', tab_kind: 'home' }))).toBe('none');
    expect(resolveTabDetachBehavior(buildTab({ configuration: { detach_behavior: 'unknown' } }))).toBe('none');
    expect(resolveTabDetachBehavior(buildTab({ configuration: { detach_behavior: 42 } }))).toBe('none');
  });

  it('resolves the Agent Tasks placeholder renderer', () => {
    const tab = buildTab({ id: 'agent_tasks', configuration: { capability_id: 'agent_tasks.history' } });
    expect(resolveTabRenderer(tab)).not.toBeNull();
    expect(resolveTabDetachBehavior(tab)).toBe('none');
  });
});
