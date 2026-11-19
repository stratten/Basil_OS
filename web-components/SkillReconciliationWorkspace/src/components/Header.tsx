import { WindowControlButton } from '@shared/windowChrome/WindowControlButton';
import { WindowMoveHandle } from '@shared/windowChrome/WindowMoveHandle';

interface HeaderProps {
  summary: string;
  isCollapsed: boolean;
  onMinimize: () => void;
  onClose: () => void;
  onToggleCollapse: () => void;
}

export function Header({ summary, isCollapsed, onMinimize, onClose, onToggleCollapse }: HeaderProps) {
  return (
    <div className="widget-header window-move-host">
      <WindowMoveHandle />
      <div className="header-left">
        <WindowControlButton kind="close" label="Close" className="header-btn" onClick={onClose} />
        <WindowControlButton kind="minimize" label="Minimize" className="header-btn" onClick={onMinimize} />
        <WindowControlButton
          kind="collapse"
          label={isCollapsed ? 'Expand' : 'Collapse'}
          className="header-btn"
          collapsed={isCollapsed}
          pressed={isCollapsed}
          onClick={onToggleCollapse}
        />
        <span className="header-title">Skill Reconciliation</span>
      </div>
      <div className="header-right">
        <span className="header-summary">{summary}</span>
      </div>
    </div>
  );
}
