import {
  HistoryFilterButton,
  HistoryFilterPanel,
  type HistoryFilterField,
} from '@shared/historyFilters/HistoryFilterControls';
import {
  countActiveFilters,
  type DocumentsFilter,
  type SidebarFilters as SidebarFilterState,
  type SourceFilter,
  type StatusFilter,
  type TurnsFilter,
} from './sidebarFilters';

export const SIDEBAR_FILTER_PANEL_ID = 'task-sidebar-filters';

const SOURCE_OPTIONS = [
  { value: 'any', label: 'Any source' },
  { value: 'direct', label: 'Asked directly' },
  { value: 'conversation', label: 'From a conversation' },
  { value: 'todo', label: 'From a to-do' },
  { value: 'meeting', label: 'From a meeting' },
  { value: 'scheduled', label: 'Scheduled' },
] as const satisfies readonly { value: SourceFilter; label: string }[];

const STATUS_OPTIONS = [
  { value: 'any', label: 'Any status' },
  { value: 'active', label: 'Running or waiting' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'canceled', label: 'Canceled' },
] as const satisfies readonly { value: StatusFilter; label: string }[];

const DOCUMENT_OPTIONS = [
  { value: 'any', label: 'Any' },
  { value: 'yes', label: 'Has documents' },
  { value: 'no', label: 'No documents' },
] as const satisfies readonly { value: DocumentsFilter; label: string }[];

const TURN_OPTIONS = [
  { value: 'any', label: 'Any' },
  { value: 'single', label: 'One turn' },
  { value: 'follow_ups', label: 'Has follow-ups' },
] as const satisfies readonly { value: TurnsFilter; label: string }[];

interface FilterButtonProps {
  filters: SidebarFilterState;
  expanded: boolean;
  onToggle: () => void;
}

/** The funnel button beside the search box; its badge counts the filters currently narrowing the list. */
export function SidebarFilterButton({ filters, expanded, onToggle }: FilterButtonProps) {
  return (
    <HistoryFilterButton
      activeCount={countActiveFilters(filters)}
      expanded={expanded}
      onToggle={onToggle}
      panelId={SIDEBAR_FILTER_PANEL_ID}
      label="Task filters"
      title="Filter tasks"
    />
  );
}

interface FilterPanelProps {
  filters: SidebarFilterState;
  expanded: boolean;
  onChange: (change: Partial<SidebarFilterState>) => void;
  onClear: () => void;
}

export function SidebarFilterPanel({ filters, expanded, onChange, onClear }: FilterPanelProps) {
  const fieldRows: HistoryFilterField[][] = [
    [{ kind: 'select', key: 'source', label: 'Source', value: filters.source, options: SOURCE_OPTIONS }],
    [{ kind: 'select', key: 'status', label: 'Status', value: filters.status, options: STATUS_OPTIONS }],
    [{ kind: 'text', key: 'app', label: 'Application', value: filters.app, placeholder: 'Captured in an app named...' }],
    [
      { kind: 'select', key: 'documents', label: 'Documents', value: filters.documents, options: DOCUMENT_OPTIONS },
      { kind: 'select', key: 'turns', label: 'Turns', value: filters.turns, options: TURN_OPTIONS },
    ],
  ];
  return (
    <HistoryFilterPanel
      panelId={SIDEBAR_FILTER_PANEL_ID}
      label="Task filters"
      expanded={expanded}
      startDate={filters.startDate}
      endDate={filters.endDate}
      fieldRows={fieldRows}
      activeCount={countActiveFilters(filters)}
      // Every key the panel reports is a SidebarFilters key whose value type matches the field that produced it.
      onChange={change => onChange(change as Partial<SidebarFilterState>)}
      onClear={onClear}
    />
  );
}
