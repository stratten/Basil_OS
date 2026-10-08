import { WindowControlButton } from '@shared/WindowControlButton';

interface HeaderProps {
  summary: string;
  isCollapsed: boolean;
  onMinimize: () => void;
  onClose: () => void;
  onToggleCollapse: () => void;
}

export function Header({ summary, isCollapsed, onMinimize, onClose, onToggleCollapse }: HeaderProps) {
  return (
    <div className="widget-header">
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
