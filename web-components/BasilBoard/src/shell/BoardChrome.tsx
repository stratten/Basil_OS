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
      return <svg {...iconProps}><path d="M2 7.5 8 2.5l6 5V14a1 1 0 0 1-1 1h-3.5v-4H6.5v4H3a1 1 0 0 1-1-1V7.5z" /></svg>;
    case 'chat':
      return <svg {...iconProps}><path d="M2.5 3.5h11v7h-6L4.5 13v-2.5h-2z" /></svg>;
    case 'meetings':
      return <svg {...iconProps}><rect x="2.5" y="3.5" width="11" height="10" rx="1.5" /><path d="M5 2.5v2M11 2.5v2M2.5 6.5h11M5 9h2M9 9h2M5 11.5h2" /></svg>;
    case 'agent_tasks':
      return <svg {...iconProps}><rect x="3" y="2.5" width="10" height="11" rx="1.5" /><path d="M6 6.5h4M6 9h4M6 11.5h2.5" /></svg>;
    case 'checklist':
      return <svg {...iconProps}><rect x="3" y="2.5" width="10" height="11" rx="1.5" /><path d="m5 6.3.8.8 1.3-1.5M8.5 6.5h2.5M5 9.7l.8.8L7.1 9M8.5 10h2.5" /></svg>;
    default:
      return <svg {...iconProps}><rect x="2.5" y="2.5" width="11" height="11" rx="2" /></svg>;
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
  const bubbleRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const reportGeometry = () => {
      const railRect = tabRailRef.current?.getBoundingClientRect();
      const bubbleRect = bubbleRef.current?.getBoundingClientRect();
      if (!railRect || !bubbleRect) return;
      reportBoardChromeGeometry({ contentLeft: railRect.right, contentTop: bubbleRect.bottom });
    };
    reportGeometry();
    window.addEventListener('resize', reportGeometry);
    return () => window.removeEventListener('resize', reportGeometry);
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
      <header className="basil-board-header">
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
          <div className="basil-board-bubble" ref={bubbleRef}>
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
