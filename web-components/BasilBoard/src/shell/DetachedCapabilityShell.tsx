import { useMemo, useState } from 'react';
import { WindowControlButton } from '@shared/WindowControlButton';
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
