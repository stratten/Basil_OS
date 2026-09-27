import { useState, type ReactNode } from 'react'

interface BasilWindowChromeProps {
  title: string
  children: ReactNode
  onClose: () => void
  onMinimize: () => void
  onCollapse: () => void
  onExpand: () => void
}

export function BasilWindowChrome({ title, children, onClose, onMinimize, onCollapse, onExpand }: BasilWindowChromeProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  const toggleCollapsed = () => {
    const next = !isCollapsed
    setIsCollapsed(next)
    if (next) {
      onCollapse()
    } else {
      onExpand()
    }
  }

  return (
    <div className="basil-webkit-window-frame">
      <div className="basil-window-surface basil-webkit-window-surface">
        <header className="basil-window-header">
          <div className="basil-window-controls">
            <button type="button" className="basil-window-control" onClick={() => onClose()} title="Close" aria-label="Close window">
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="rgba(51, 85, 155, 0.15)" />
                <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <button type="button" className="basil-window-control" onClick={() => onMinimize()} title="Minimize" aria-label="Minimize window">
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="rgba(51, 85, 155, 0.15)" />
                <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <button
              type="button"
              className="basil-window-control"
              onClick={toggleCollapsed}
              title={isCollapsed ? 'Expand' : 'Collapse'}
              aria-label={isCollapsed ? 'Expand window' : 'Collapse window'}
              aria-pressed={isCollapsed}
            >
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="rgba(51, 85, 155, 0.15)" />
                <path
                  className={`basil-window-collapse-chevron${isCollapsed ? ' is-collapsed' : ''}`}
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
          <span className="basil-window-title">{title}</span>
        </header>
        <div
          className={`basil-window-content${isCollapsed ? ' is-collapsed' : ''}`}
          aria-hidden={isCollapsed}
          {...(isCollapsed ? { inert: '' } : {})}
        >
          {children}
        </div>
      </div>
    </div>
  )
}
