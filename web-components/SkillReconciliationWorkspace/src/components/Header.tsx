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
        <button className="header-btn" onClick={onClose} title="Close">
          <svg width="20" height="20" viewBox="0 0 22 22">
            <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
            <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
        <button className="header-btn" onClick={onMinimize} title="Minimize">
          <svg width="20" height="20" viewBox="0 0 22 22">
            <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
            <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
        <button
          className="header-btn"
          onClick={onToggleCollapse}
          title={isCollapsed ? 'Expand' : 'Collapse'}
          aria-pressed={isCollapsed}
        >
          <svg width="20" height="20" viewBox="0 0 22 22">
            <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
            <path
              className={`header-collapse-chevron${isCollapsed ? ' is-collapsed' : ''}`}
              d="M7 9l4 4 4-4"
              fill="none"
              stroke="var(--secondary)"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <span className="header-title">Skill Reconciliation</span>
      </div>
      <div className="header-right">
        <span className="header-summary">{summary}</span>
      </div>
    </div>
  );
}
