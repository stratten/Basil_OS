import {
  HistoryFilterButton,
  HistoryFilterPanel,
  type HistoryFilterField,
} from '@shared/historyFilters/HistoryFilterControls';
import {
  countActiveConversationFilters,
  type AgentWorkFilter,
  type ConversationFilters,
  type LengthFilter,
} from './conversationFilters';

export const CONVERSATION_FILTER_PANEL_ID = 'chats-sidebar-filters';

const AGENT_WORK_OPTIONS = [
  { value: 'any', label: 'Any' },
  { value: 'none', label: 'No agent work' },
  { value: 'has', label: 'Used an agent' },
  { value: 'active', label: 'Agent running or waiting' },
  { value: 'failed', label: 'Agent failed' },
] as const satisfies readonly { value: AgentWorkFilter; label: string }[];

const LENGTH_OPTIONS = [
  { value: 'any', label: 'Any' },
  { value: 'single', label: 'One exchange' },
  { value: 'multi', label: 'Several exchanges' },
] as const satisfies readonly { value: LengthFilter; label: string }[];

/** Everything the sidebar needs to render and drive the conversation filters. */
export interface ConversationSidebarFilters {
  filters: ConversationFilters;
  expanded: boolean;
  onChange: (change: Partial<ConversationFilters>) => void;
  onClear: () => void;
  onToggle: () => void;
}

/** The funnel button beside the search box; its badge counts the filters currently narrowing the list. */
export function ConversationFilterButton({ filters, expanded, onToggle }: Pick<ConversationSidebarFilters, 'filters' | 'expanded' | 'onToggle'>) {
  return (
    <HistoryFilterButton
      activeCount={countActiveConversationFilters(filters)}
      expanded={expanded}
      onToggle={onToggle}
      panelId={CONVERSATION_FILTER_PANEL_ID}
      label="Conversation filters"
      title="Filter conversations"
    />
  );
}

export function ConversationFilterPanel({ filters, expanded, onChange, onClear }: Omit<ConversationSidebarFilters, 'onToggle'>) {
  const fieldRows: HistoryFilterField[][] = [
    [{ kind: 'select', key: 'agentWork', label: 'Agent work', value: filters.agentWork, options: AGENT_WORK_OPTIONS }],
    [{ kind: 'select', key: 'length', label: 'Length', value: filters.length, options: LENGTH_OPTIONS }],
  ];
  return (
    <HistoryFilterPanel
      panelId={CONVERSATION_FILTER_PANEL_ID}
      label="Conversation filters"
      expanded={expanded}
      startDate={filters.startDate}
      endDate={filters.endDate}
      fieldRows={fieldRows}
      activeCount={countActiveConversationFilters(filters)}
      // Every key the panel reports is a ConversationFilters key whose value type matches the field that produced it.
      onChange={change => onChange(change as Partial<ConversationFilters>)}
      onClear={onClear}
    />
  );
}
