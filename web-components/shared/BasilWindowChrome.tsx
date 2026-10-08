import { useState, type ReactNode } from 'react'
import { useCollapseShortcut } from './useCollapseShortcut'
import { useSettledExpand } from './useSettledExpand'
import { WindowControlButton } from './WindowControlButton'

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
  const isContentCollapsed = useSettledExpand(isCollapsed)

  const toggleCollapsed = () => {
    const next = !isCollapsed
    setIsCollapsed(next)
    if (next) {
      onCollapse()
    } else {
      onExpand()
    }
  }

  useCollapseShortcut(toggleCollapsed)

  return (
    <div className="basil-webkit-window-frame">
      <div className="basil-window-surface basil-webkit-window-surface">
        <header className="basil-window-header">
          <div className="basil-window-controls">
            <WindowControlButton kind="close" label="Close window" className="basil-window-control" onClick={onClose} />
            <WindowControlButton kind="minimize" label="Minimize window" className="basil-window-control" onClick={onMinimize} />
            <WindowControlButton
              kind="collapse"
              label={isCollapsed ? 'Expand window' : 'Collapse window'}
              className="basil-window-control"
              collapsed={isCollapsed}
              pressed={isCollapsed}
              onClick={toggleCollapsed}
            />
          </div>
          <span className="basil-window-title">{title}</span>
        </header>
        <div
          className={`basil-window-content${isContentCollapsed ? ' is-collapsed' : ''}`}
          aria-hidden={isContentCollapsed}
          {...(isContentCollapsed ? { inert: '' } : {})}
        >
          {children}
        </div>
      </div>
    </div>
  )
}
