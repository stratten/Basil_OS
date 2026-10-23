import { useState, type ReactNode } from 'react';
import { WindowControlButton } from '@shared/WindowControlButton';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';
import { requestWindowClose, requestWindowCollapse, requestWindowExpand, requestWindowMinimize } from '../services/bridge';

interface ConversationWindowChromeProps {
  children: ReactNode;
  subtitle?: string;
}

export default function ConversationWindowChrome({
  children,
  subtitle,
}: ConversationWindowChromeProps) {
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
    <div className="basil-webkit-window-frame conversation-standalone-frame">
      <div className={`basil-board-root basil-board-detached-shell basil-webkit-window-surface${isContentCollapsed ? ' is-collapsed' : ''}`}>
        <header className="basil-board-detached-header">
          <div className="conversation-window-header-left">
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
            <svg className="conversation-window-feature-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.35" aria-hidden="true">
              <circle cx="10" cy="10" r="8" />
              <path d="M6.1 7.1A1.6 1.6 0 0 1 7.7 5.5h4.6a1.6 1.6 0 0 1 1.6 1.6v3.25a1.6 1.6 0 0 1-1.6 1.6H9.2L6.5 14v-2.05a1.6 1.6 0 0 1-.4-1.05Z" strokeLinejoin="round" />
            </svg>
            <div className="conversation-window-identity">
              <span className="basil-board-detached-title">Conversation</span>
              <span className={`conversation-window-subtitle${subtitle ? '' : ' is-empty'}`}>
                {subtitle || '\u00A0'}
              </span>
            </div>
          </div>
        </header>
        <main
          className={`basil-board-content${isContentCollapsed ? ' is-collapsed' : ''}`}
          aria-hidden={isContentCollapsed}
          inert={isContentCollapsed ? '' : undefined}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
