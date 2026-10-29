import NativeSymbolIcon from './NativeSymbolIcon';
import './history-sidebar-controls.css';

export function HistorySidebarHeader({
  title,
  onStartNew,
  onCollapse,
  startLabel,
  collapseLabel,
  classNames = {},
}: {
  title: string;
  onStartNew: () => void;
  onCollapse: () => void;
  startLabel: string;
  collapseLabel: string;
  classNames?: Partial<{ root: string; title: string; actions: string; button: string; symbol: string }>;
}) {
  return <div className={`shared-history-sidebar-header ${classNames.root ?? ''}`.trim()}>
    <span className={`shared-history-sidebar-title ${classNames.title ?? ''}`.trim()}>{title}</span>
    <span className={`shared-history-sidebar-header-actions ${classNames.actions ?? ''}`.trim()}>
      <button type="button" className={`shared-history-sidebar-icon-button ${classNames.button ?? ''}`.trim()} onClick={onStartNew} aria-label={startLabel} title={startLabel}><NativeSymbolIcon name="conversationNew" className={classNames.symbol} /></button>
      <button type="button" className={`shared-history-sidebar-icon-button ${classNames.button ?? ''}`.trim()} onClick={onCollapse} aria-label={collapseLabel} title={collapseLabel}><NativeSymbolIcon name="conversationSidebar" className={classNames.symbol} /></button>
    </span>
  </div>;
}

export function HistorySearchField({
  value,
  onChange,
  placeholder,
  ariaLabel,
  onClear,
  classNames = {},
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  onClear?: () => void;
  classNames?: Partial<{ root: string; input: string; icon: string }>;
}) {
  return <label className={`shared-history-search-shell ${classNames.root ?? ''}`.trim()}>
    <SearchIcon className={classNames.icon} />
    <input className={classNames.input} type="search" value={value} placeholder={placeholder} aria-label={ariaLabel} onChange={(event) => onChange(event.target.value)} />
    {value && onClear && <button type="button" onClick={onClear} aria-label="Clear search">×</button>}
  </label>;
}

export function CollapsedHistoryRail({ ariaLabel, title, onExpand, classNames = {} }: { ariaLabel: string; title: string; onExpand: () => void; classNames?: Partial<{ root: string; button: string; symbol: string }> }) {
  return <div className={`shared-history-rail ${classNames.root ?? ''}`.trim()}>
    <button type="button" className={classNames.button} onClick={onExpand} aria-label={ariaLabel} title={title}><NativeSymbolIcon name="conversationSidebarExpand" className={classNames.symbol} /></button>
  </div>;
}

function SearchIcon({ className }: { className?: string }) {
  return <svg className={`shared-history-search-icon ${className ?? ''}`.trim()} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.2" /><path d="m10 10 3.2 3.2" strokeLinecap="round" /></svg>;
}
