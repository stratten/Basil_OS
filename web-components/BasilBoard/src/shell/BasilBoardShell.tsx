import { useEffect, useMemo, useState } from 'react';
import type { AgentTaskOriginNavigationPayload, BasilBoardTab } from '../contracts';
import { rejectUnknownTabKind } from '../home/homeReducer';
import {
  bringBasilBoardTabToFront,
  registerDetachedTabsChangedHandler,
} from '../services/bridge';
import BoardChrome from './BoardChrome';
import { resolveTabDetachBehavior, resolveTabRenderer } from './TabRegistry';

interface BasilBoardShellProps {
  tabs: BasilBoardTab[];
  originNavigation?: AgentTaskOriginNavigationPayload;
}

export default function BasilBoardShell({ tabs, originNavigation }: BasilBoardShellProps) {
  const activeTabs = useMemo(
    () => tabs.filter((tab) => tab.status === 'active').sort((a, b) => a.position - b.position),
    [tabs],
  );
  const [activeTabId, setActiveTabId] = useState(activeTabs[0]?.id ?? 'home');
  const [detachedTabIds, setDetachedTabIds] = useState<Set<string>>(new Set());
  const activeTab = activeTabs.find((tab) => tab.id === activeTabId) ?? activeTabs[0];
  const renderer = activeTab ? resolveTabRenderer(activeTab) : null;
  const activeTabDetachBehavior = activeTab ? resolveTabDetachBehavior(activeTab) : 'none';
  const isActiveTabDetachedElsewhere = Boolean(activeTab && detachedTabIds.has(activeTab.id));

  const selectTab = (tabId: string) => {
    setActiveTabId(tabId);
    const selectedTab = activeTabs.find((tab) => tab.id === tabId);
    const selectedDetachBehavior = selectedTab ? resolveTabDetachBehavior(selectedTab) : 'none';
    if (selectedDetachBehavior === 'useBoardWindow' && detachedTabIds.has(tabId)) {
      bringBasilBoardTabToFront(tabId);
    }
  };

  useEffect(
    () =>
      registerDetachedTabsChangedHandler((payload) => {
        setDetachedTabIds(new Set(payload.detachedTabIds));
      }),
    [],
  );

  useEffect(() => {
    if (!originNavigation) return;
    const targetTabId = originNavigation.originType === 'meeting'
      ? 'meetings'
      : originNavigation.originType === 'scheduled_task'
        ? 'agent_tasks'
        : originNavigation.originType === 'conversation'
          ? 'chats'
          : 'todos';
    if (activeTabs.some(tab => tab.id === targetTabId)) {
      setActiveTabId(targetTabId);
    }
  }, [activeTabs, originNavigation]);

  return (
    <BoardChrome
      tabs={activeTabs}
      activeTabId={activeTab?.id ?? 'home'}
      onSelectTab={selectTab}
      activeTabDetachBehavior={activeTabDetachBehavior}
      activeTabDetached={isActiveTabDetachedElsewhere}
    >
      <main className="basil-board-content">
        {!activeTab || rejectUnknownTabKind(activeTab.tab_kind) ? (
          <div className="home-unavailable-state">This tab is unavailable.</div>
        ) : isActiveTabDetachedElsewhere ? (
          <div className="home-unavailable-state basil-board-detached-placeholder">
            <p>{activeTab.title} is open in its own window.</p>
          </div>
        ) : renderer ? (
          renderer({ tab: activeTab, originNavigation })
        ) : (
          <div className="home-unavailable-state">No renderer registered for this tab.</div>
        )}
      </main>
    </BoardChrome>
  );
}
