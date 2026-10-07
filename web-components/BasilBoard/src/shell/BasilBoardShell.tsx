import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AgentTaskOriginNavigationPayload, BasilBoardTab } from '../contracts';
import { HomeForwardContext } from '../home/HomeForwardContext';
import { rejectUnknownTabKind } from '../home/homeReducer';
import { useHomeRuntime } from '../home/HomeRuntimeContext';
import RoutedNotice from '../home/RoutedNotice';
import { useHomeForwarding } from '../home/useHomeForwarding';
import {
  bringBasilBoardTabToFront,
  registerBoardTabNavigationHandler,
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

  const hasTab = useCallback((tabId: string) => activeTabs.some((tab) => tab.id === tabId), [activeTabs]);
  const { contextValue: homeForward, notice, dismissNotice, reroute, setNoticeEngaged } = useHomeForwarding({
    hasTab,
    selectTab: setActiveTabId,
  });

  const { voiceTurn } = useHomeRuntime();
  const forwardedVoiceTurnVersion = useRef(voiceTurn?.version ?? 0);
  const { forwardTurn } = homeForward;
  useEffect(() => {
    if (!voiceTurn || voiceTurn.version === forwardedVoiceTurnVersion.current) return;
    forwardedVoiceTurnVersion.current = voiceTurn.version;
    try {
      forwardTurn(voiceTurn.response, voiceTurn.submission);
    } catch (error) {
      console.error('[BasilBoardShell] Voice turn could not be forwarded:', error);
    }
  }, [forwardTurn, voiceTurn]);

  useEffect(
    () =>
      registerBoardTabNavigationHandler(({ tabId }) => {
        if (hasTab(tabId)) setActiveTabId(tabId);
      }),
    [hasTab],
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
    <HomeForwardContext.Provider value={homeForward}>
    <BoardChrome
      tabs={activeTabs}
      activeTabId={activeTab?.id ?? 'home'}
      onSelectTab={selectTab}
      activeTabDetachBehavior={activeTabDetachBehavior}
      activeTabDetached={isActiveTabDetachedElsewhere}
    >
      <main className="basil-board-content">
        {notice ? (
          <RoutedNotice
            notice={notice}
            onReroute={() => void reroute()}
            onDismiss={dismissNotice}
            onEngagedChange={setNoticeEngaged}
          />
        ) : null}
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
    </HomeForwardContext.Provider>
  );
}
