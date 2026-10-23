import { useEffect, useRef, useState, type ReactNode } from 'react';
import { WindowControlButton } from '@shared/WindowControlButton';
import AnimatedBubble from '@shared/bubble/AnimatedBubble';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';
import type { BasilBoardTab, BasilBoardTabDetachBehavior } from '../contracts';
import { useHomeRuntime } from '../home/HomeRuntimeContext';
import {
  detachBasilBoardTab,
  openNativeBasilBoardTabWindow,
  reportBoardChromeGeometry,
  requestWindowClose,
  requestWindowCollapse,
  requestWindowExpand,
  requestWindowMinimize,
} from '../services/bridge';

interface BoardChromeProps {
  tabs: BasilBoardTab[];
  activeTabId: string;
  onSelectTab: (tabId: string) => void;
  activeTabDetachBehavior?: BasilBoardTabDetachBehavior;
  activeTabDetached?: boolean;
  children: ReactNode;
}

function tabIconKey(tab: BasilBoardTab): string {
  return tab.icon_key ?? 'home';
}

function TabIcon({ iconKey }: { iconKey: string }) {
  const iconProps = {
    width: '18',
    height: '18',
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: '1.3',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };

  switch (iconKey) {
    case 'home':
      return <svg {...iconProps}><path d="M2.5 7.6 7.2 3.4a1.1 1.1 0 0 1 1.6 0L13.5 7.6v5.2a1.7 1.7 0 0 1-1.7 1.7H10v-3a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1v3H4.2a1.7 1.7 0 0 1-1.7-1.7Z" /></svg>;
    case 'chat':
      return <svg {...iconProps}><path d="M4.7 2.8h6.6a2.2 2.2 0 0 1 2.2 2.2v3.6a2.2 2.2 0 0 1-2.2 2.2H8l-2.8 2.4v-2.4h-.5A2.2 2.2 0 0 1 2.5 8.6V5a2.2 2.2 0 0 1 2.2-2.2Z" /></svg>;
    case 'meetings':
      return <svg {...iconProps}><rect x="2.5" y="3.5" width="11" height="10" rx="2.2" /><path d="M5 2.5v2M11 2.5v2M2.5 6.5h11M5 9h2M9 9h2M5 11.5h2" /></svg>;
    case 'agent_tasks':
      return <svg {...iconProps}><rect x="3" y="5.5" width="10" height="7.5" rx="2.2" /><path d="M8 5.5V3.4M1.8 8.6v2M14.2 8.6v2M6.3 11q1.7 1.1 3.4 0" /><circle cx="8" cy="2.5" r=".9" fill="currentColor" stroke="none" /><circle cx="6" cy="8.5" r=".8" fill="currentColor" stroke="none" /><circle cx="10" cy="8.5" r=".8" fill="currentColor" stroke="none" /></svg>;
    case 'checklist':
      return <svg {...iconProps}><rect x="2.5" y="2.5" width="11" height="11" rx="2.2" /><path d="m5.4 8.2 1.9 1.9 3.4-3.9" /></svg>;
    default:
      return <svg {...iconProps}><rect x="2.5" y="2.5" width="11" height="11" rx="2.2" /></svg>;
  }
}

export default function BoardChrome({
  tabs,
  activeTabId,
  onSelectTab,
  activeTabDetachBehavior = 'none',
  activeTabDetached = false,
  children,
}: BoardChromeProps) {
  const { voiceState, statusIconDataUrl } = useHomeRuntime();
  const activeTab = tabs.find((tab) => tab.id === activeTabId);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isContentCollapsed = useSettledExpand(isCollapsed);
  const tabRailRef = useRef<HTMLElement | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // Native embedded hosts (Agent Tasks, Notetaker) are laid over this chrome, so they must start below the header's bottom border, not the bubble's bottom edge (8px higher), or they cover the border. The header's height changes when its border is added or removed on collapse and expand, so it is observed in addition to window resizes.
    const reportGeometry = () => {
      const railRect = tabRailRef.current?.getBoundingClientRect();
      const headerRect = headerRef.current?.getBoundingClientRect();
      if (!railRect || !headerRect) return;
      reportBoardChromeGeometry({ contentLeft: railRect.right, contentTop: headerRect.bottom });
    };
    reportGeometry();
    window.addEventListener('resize', reportGeometry);
    const headerElement = headerRef.current;
    const headerObserver = headerElement && typeof globalThis.ResizeObserver !== 'undefined'
      ? new globalThis.ResizeObserver(reportGeometry)
      : null;
    if (headerElement) headerObserver?.observe(headerElement);
    return () => {
      window.removeEventListener('resize', reportGeometry);
      headerObserver?.disconnect();
    };
  }, []);

  const isCapturing = voiceState === 'recording' || voiceState === 'starting';
  const isProcessing = voiceState === 'processing';
  const bubbleMode = isCapturing ? 'audioResponsive' : isProcessing ? 'processing' : 'ambient';

  const bubbleBase = isCapturing
    ? 'var(--recording-base)'
    : isProcessing
      ? 'var(--processing-base)'
      : 'var(--ready-base)';
  const bubbleAccent = isCapturing
    ? 'var(--recording-accent)'
    : isProcessing
      ? 'var(--processing-accent)'
      : 'var(--ready-accent)';

  const detachActiveTab = () => {
    if (!activeTab) return;
    if (activeTabDetachBehavior === 'useBoardWindow') {
      detachBasilBoardTab(activeTab.id);
      return;
    }
    if (activeTabDetachBehavior === 'useNativeWindow') {
      openNativeBasilBoardTabWindow(activeTab.id);
    }
  };

  const toggleCollapsed = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    if (next) {
      requestWindowCollapse();
    } else {
      requestWindowExpand();
    }
  };

  useCollapseShortcut(toggleCollapsed);

  return (
    <div className="basil-webkit-window-frame">
      <div className={`basil-board-root basil-webkit-window-surface${isContentCollapsed ? ' is-collapsed' : ''}`}>
      <header className="basil-board-header" ref={headerRef}>
        <div className="basil-board-header-left">
          <div className="basil-board-window-controls">
            <WindowControlButton kind="close" label="Close" className="basil-board-window-control" onClick={requestWindowClose} />
            <WindowControlButton kind="minimize" label="Minimize" className="basil-board-window-control" onClick={requestWindowMinimize} />
            <WindowControlButton
              kind="collapse"
              label={isCollapsed ? 'Expand' : 'Collapse'}
              className="basil-board-window-control"
              collapsed={isCollapsed}
              pressed={isCollapsed}
              onClick={toggleCollapsed}
            />
            {statusIconDataUrl ? (
              <img className="basil-board-brand-icon" src={statusIconDataUrl} alt="" aria-hidden="true" />
            ) : (
              <span className="basil-board-brand-fallback" aria-hidden="true">B</span>
            )}
          </div>
          <div className="basil-board-identity">
            <span className="basil-board-title">Basil</span>
            {activeTab && activeTab.id !== 'home' ? (
              <span className="basil-board-context">{activeTab.title}</span>
            ) : null}
          </div>
        </div>
        <div className="basil-board-header-right">
          {activeTabDetachBehavior !== 'none' ? (
            <button
              type="button"
              className="basil-board-detach-button"
              onClick={detachActiveTab}
              disabled={activeTabDetachBehavior === 'useBoardWindow' && activeTabDetached}
              title={activeTabDetachBehavior === 'useBoardWindow' && activeTabDetached
                ? 'Already open in its own window'
                : 'Open in a separate window'}
              aria-label={`Open ${activeTab?.title ?? 'tab'} in a separate window`}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 2.5H3.5A1.5 1.5 0 0 0 2 4v8.5A1.5 1.5 0 0 0 3.5 14H12a1.5 1.5 0 0 0 1.5-1.5V10" />
                <path d="M9 2h5v5" /><path d="M14 2L7 9" />
              </svg>
            </button>
          ) : null}
          <div className="basil-board-bubble">
            <AnimatedBubble
              size={44}
              mode={bubbleMode}
              baseColor={bubbleBase}
              accentColor={bubbleAccent}
              audioLevel={0}
            />
          </div>
        </div>
      </header>
      <div className={`basil-board-body${isContentCollapsed ? ' is-collapsed' : ''}`} aria-hidden={isContentCollapsed} inert={isContentCollapsed ? '' : undefined}>
        <nav className="basil-board-tabs" aria-label="Basil board tabs" ref={tabRailRef}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`basil-board-tab ${tab.id === activeTabId ? 'is-active' : ''}`}
              onClick={() => onSelectTab(tab.id)}
              aria-label={tab.title}
              aria-current={tab.id === activeTabId ? 'page' : undefined}
              title={tab.title}
            >
              <TabIcon iconKey={tabIconKey(tab)} />
            </button>
          ))}
        </nav>
        {children}
      </div>
    </div>
    </div>
  );
}
