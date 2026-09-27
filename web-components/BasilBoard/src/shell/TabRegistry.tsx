import type { AgentTaskOriginNavigationPayload, BasilBoardTab, BasilBoardTabDetachBehavior } from '../contracts';
import { rejectUnknownTabKind } from '../home/homeReducer';
import AgentTasksHostPlaceholder from '../capabilities/AgentTasksHostPlaceholder';
import ChatsTab from '../capabilities/ChatsTab';
import HomeView from '../home/HomeView';
import MeetingsTab from '../capabilities/MeetingsTab';
import TodoView from '../todos/TodoView';

export type TabRenderer = (props: {
  tab: BasilBoardTab;
  originNavigation?: AgentTaskOriginNavigationPayload;
}) => JSX.Element | null;

const kindRenderers: Record<string, TabRenderer> = {
  home: () => <HomeView />,
};

const capabilityRenderers: Record<string, TabRenderer> = {
  'todos.workspace': ({ originNavigation }) => <TodoView originNavigation={originNavigation} />,
  'conversations.history': ({ originNavigation }) => <ChatsTab originNavigation={originNavigation} />,
  'meetings.history': () => <MeetingsTab />,
  'agent_tasks.history': () => <AgentTasksHostPlaceholder />,
};

const detachBehaviors = new Set<BasilBoardTabDetachBehavior>([
  'useBoardWindow',
  'useNativeWindow',
  'none',
]);

export function resolveTabDetachBehavior(tab: BasilBoardTab): BasilBoardTabDetachBehavior {
  const value = tab.configuration?.detach_behavior;
  return typeof value === 'string' && detachBehaviors.has(value as BasilBoardTabDetachBehavior)
    ? value as BasilBoardTabDetachBehavior
    : 'none';
}

export function resolveTabRenderer(tab: BasilBoardTab): TabRenderer | null {
  if (rejectUnknownTabKind(tab.tab_kind)) {
    return null;
  }
  if (tab.tab_kind === 'capability') {
    const capabilityId = tab.configuration?.capability_id;
    return typeof capabilityId === 'string' ? capabilityRenderers[capabilityId] ?? null : null;
  }
  return kindRenderers[tab.tab_kind] ?? null;
}

export { HomeView };
