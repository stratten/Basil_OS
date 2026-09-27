import { useState, type ReactNode } from 'react';
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

  const toggleCollapsed = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    if (next) {
      requestWindowCollapse();
    } else {
      requestWindowExpand();
    }
  };

  return (
    <div className="basil-webkit-window-frame conversation-standalone-frame">
      <div className={`basil-board-root basil-board-detached-shell basil-webkit-window-surface${isCollapsed ? ' is-collapsed' : ''}`}>
        <header className="basil-board-detached-header">
          <div className="conversation-window-header-left">
            <div className="basil-board-window-controls">
              <button
                type="button"
                className="basil-board-window-control"
                onClick={requestWindowClose}
                title="Close"
                aria-label="Close"
              >
                <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                  <circle cx="11" cy="11" r="10" fill="var(--conversation-window-control-fill)" />
                  <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                  <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
              <button
                type="button"
                className="basil-board-window-control"
                onClick={requestWindowMinimize}
                title="Minimize"
                aria-label="Minimize"
              >
                <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                  <circle cx="11" cy="11" r="10" fill="var(--conversation-window-control-fill)" />
                  <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
              <button
                type="button"
                className="basil-board-window-control"
                onClick={toggleCollapsed}
                title={isCollapsed ? 'Expand' : 'Collapse'}
                aria-label={isCollapsed ? 'Expand' : 'Collapse'}
                aria-pressed={isCollapsed}
              >
                <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                  <circle cx="11" cy="11" r="10" fill="var(--conversation-window-control-fill)" />
                  <path
                    className={`conversation-window-collapse-chevron${isCollapsed ? ' is-collapsed' : ''}`}
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
          className={`basil-board-content${isCollapsed ? ' is-collapsed' : ''}`}
          aria-hidden={isCollapsed}
          inert={isCollapsed ? '' : undefined}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
