import { useMemo, useState } from 'react';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';
import type { AgentTaskOriginNavigationPayload, BasilBoardTab } from '../contracts';
import { requestWindowClose, requestWindowCollapse, requestWindowExpand, requestWindowMinimize } from '../services/bridge';
import { resolveTabRenderer } from './TabRegistry';

interface DetachedCapabilityShellProps {
  tabs: BasilBoardTab[];
  detachedTabId: string;
  originNavigation?: AgentTaskOriginNavigationPayload;
}

export default function DetachedCapabilityShell({
  tabs,
  detachedTabId,
  originNavigation,
}: DetachedCapabilityShellProps) {
  const tab = useMemo(() => tabs.find((candidate) => candidate.id === detachedTabId), [tabs, detachedTabId]);
  const renderer = tab ? resolveTabRenderer(tab) : null;
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isContentCollapsed = useSettledExpand(isCollapsed);

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
      <div className={`basil-board-root basil-board-detached-shell basil-webkit-window-surface${isContentCollapsed ? ' is-collapsed' : ''}`}>
      <header className="basil-board-detached-header">
        <div className="basil-board-window-controls">
          <button
            type="button"
            className="basil-board-window-control"
            onClick={requestWindowClose}
            aria-label="Close"
          >
            <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
              <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            className="basil-board-window-control"
            onClick={requestWindowMinimize}
            aria-label="Minimize"
          >
            <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            className="basil-board-window-control"
            onClick={toggleCollapsed}
            aria-label={isCollapsed ? 'Expand' : 'Collapse'}
            aria-pressed={isCollapsed}
          >
            <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <path
                className={`basil-board-collapse-chevron${isCollapsed ? ' is-collapsed' : ''}`}
                d="M7 9l4 4 4-4"
                fill="none"
                stroke="var(--secondary)"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
        <span className="basil-board-detached-title">{tab?.title ?? 'Basil'}</span>
      </header>
      <main className={`basil-board-content${isContentCollapsed ? ' is-collapsed' : ''}`} aria-hidden={isContentCollapsed} inert={isContentCollapsed ? '' : undefined}>
        {!tab || !renderer ? (
          <div className="home-unavailable-state">This capability is unavailable.</div>
        ) : (
          renderer({ tab, originNavigation })
        )}
      </main>
    </div>
    </div>
  );
}
