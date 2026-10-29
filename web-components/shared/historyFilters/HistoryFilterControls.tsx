import PresenceRegion from '../PresenceRegion';
import TokenizedSelect from '../TokenizedSelect';
import './history-filters.css';

export interface HistoryFilterOption {
  value: string;
  label: string;
}

export interface HistoryFilterSelectField {
  kind: 'select';
  /** The key of the filter object this field edits. */
  key: string;
  label: string;
  value: string;
  options: readonly HistoryFilterOption[];
}

export interface HistoryFilterTextField {
  kind: 'text';
  key: string;
  label: string;
  value: string;
  placeholder: string;
}

export type HistoryFilterField = HistoryFilterSelectField | HistoryFilterTextField;

interface HistoryFilterButtonProps {
  activeCount: number;
  expanded: boolean;
  onToggle: () => void;
  panelId: string;
  /** Accessible name without the count, such as "Task filters". */
  label: string;
  /** Hover title, such as "Filter tasks". */
  title: string;
}

function FilterIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M2 3h12L9.4 8.2v4.1l-2.8.9V8.2L2 3Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The funnel button beside the search box; its badge counts the filters currently narrowing the list. */
export function HistoryFilterButton({ activeCount, expanded, onToggle, panelId, label, title }: HistoryFilterButtonProps) {
  return (
    <button
      type="button"
      className={`sidebar-filter-button${activeCount > 0 ? ' sidebar-filter-button--active' : ''}`}
      aria-label={activeCount > 0 ? `${label}, ${activeCount} active` : label}
      title={title}
      aria-controls={panelId}
      aria-expanded={expanded}
      onClick={onToggle}
    >
      <FilterIcon />
      {activeCount > 0 && <span className="sidebar-filter-badge">{activeCount}</span>}
    </button>
  );
}

interface HistoryFilterPanelProps {
  panelId: string;
  /** Accessible name of the panel, such as "Task filters". */
  label: string;
  expanded: boolean;
  startDate: string | null;
  endDate: string | null;
  /** Rows of fields below the date range; a row of two fields renders side by side. */
  fieldRows: readonly (readonly HistoryFilterField[])[];
  activeCount: number;
  /** Receives a one-key change, keyed by `startDate`, `endDate` or a field's `key`. */
  onChange: (change: Record<string, string | null>) => void;
  onClear: () => void;
  clearLabel?: string;
}

function renderField(field: HistoryFilterField, onChange: HistoryFilterPanelProps['onChange']) {
  return (
    <label className="sidebar-filter-field" key={field.key}>
      <span>{field.label}</span>
      {field.kind === 'select' ? (
        <TokenizedSelect
          value={field.value}
          ariaLabel={field.label}
          options={field.options}
          onValueChange={value => onChange({ [field.key]: value })}
        />
      ) : (
        <input
          type="search"
          value={field.value}
          placeholder={field.placeholder}
          aria-label={field.label}
          onChange={event => onChange({ [field.key]: event.target.value })}
        />
      )}
    </label>
  );
}

/** The collapsible filter panel: a date range, then rows of select and text fields from `fieldRows`, then Clear. */
export function HistoryFilterPanel({
  panelId,
  label,
  expanded,
  startDate,
  endDate,
  fieldRows,
  activeCount,
  onChange,
  onClear,
  clearLabel = 'Clear filters',
}: HistoryFilterPanelProps) {
  return (
    <PresenceRegion visible={expanded} className="basil-presence sidebar-filter-presence" settleWithoutTransition>
      <section id={panelId} className="sidebar-filters" aria-label={label}>
        <div className="sidebar-filter-grid">
          <label className="sidebar-filter-field">
            <span>From</span>
            <input
              type="date"
              value={startDate ?? ''}
              max={endDate ?? undefined}
              onChange={event => onChange({ startDate: event.target.value || null })}
            />
          </label>
          <label className="sidebar-filter-field">
            <span>To</span>
            <input
              type="date"
              value={endDate ?? ''}
              min={startDate ?? undefined}
              onChange={event => onChange({ endDate: event.target.value || null })}
            />
          </label>
        </div>
        {fieldRows.map(row => (row.length > 1
          ? <div className="sidebar-filter-grid" key={row.map(field => field.key).join('+')}>{row.map(field => renderField(field, onChange))}</div>
          : renderField(row[0], onChange)))}
        <button
          type="button"
          className="sidebar-filters-clear"
          disabled={activeCount === 0}
          onClick={onClear}
        >
          {clearLabel}
        </button>
      </section>
    </PresenceRegion>
  );
}
