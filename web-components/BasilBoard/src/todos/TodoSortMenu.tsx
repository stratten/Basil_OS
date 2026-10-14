import TokenizedSelect, { type TokenizedSelectOption } from '../../../shared/TokenizedSelect';
import type { TodoSortBy, TodoSortColumn, TodoSortDirection } from '../services/api';

const COLUMN_OPTIONS: readonly TokenizedSelectOption<TodoSortColumn>[] = [
  { value: 'created_at', label: 'Date created' },
  { value: 'updated_at', label: 'Last updated' },
  { value: 'due_at', label: 'Due date' },
  { value: 'title', label: 'Title' },
  { value: 'priority', label: 'Priority' },
  { value: 'status', label: 'Status' },
];

/** Mirrors the backend's per-column default direction
 * (`_TODO_SORT_DEFAULT_DIRECTION` in `repository.py`) purely for display
 * purposes -- the actual default is resolved server-side whenever
 * `direction` is omitted from the request. */
const COLUMN_DEFAULT_DIRECTION: Record<TodoSortColumn, TodoSortDirection> = {
  created_at: 'desc',
  updated_at: 'desc',
  due_at: 'asc',
  title: 'asc',
  priority: 'desc',
  status: 'asc',
};

interface TodoSortMenuProps {
  value: TodoSortBy;
  onChange: (value: TodoSortBy) => void;
}

export default function TodoSortMenu({ value, onChange }: TodoSortMenuProps) {
  const resolvedDirection = value.direction ?? COLUMN_DEFAULT_DIRECTION[value.column];

  function selectColumn(column: TodoSortColumn): void {
    onChange({ column, direction: value.column === column ? value.direction : undefined });
  }

  function toggleDirection(): void {
    onChange({ column: value.column, direction: resolvedDirection === 'asc' ? 'desc' : 'asc' });
  }

  return (
    <div className="todo-sort-menu">
      <span className="todo-sort-menu-label">Sort To-Dos</span>
      <TokenizedSelect
        className="todo-sort-menu-trigger"
        ariaLabel="Choose the To-Do sort column"
        value={value.column}
        options={COLUMN_OPTIONS}
        onValueChange={selectColumn}
      />
      <button
        type="button"
        className="todo-sort-menu-direction"
        aria-label={resolvedDirection === 'asc' ? 'Sort ascending, click to sort descending' : 'Sort descending, click to sort ascending'}
        aria-pressed={resolvedDirection === 'desc'}
        onClick={toggleDirection}
      >
        {resolvedDirection === 'asc' ? '↑' : '↓'}
      </button>
    </div>
  );
}
