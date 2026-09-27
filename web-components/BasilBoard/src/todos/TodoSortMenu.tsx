import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import type { TodoSortBy, TodoSortColumn, TodoSortDirection } from '../services/api';

const COLUMN_OPTIONS: Array<{ column: TodoSortColumn; label: string }> = [
  { column: 'created_at', label: 'Date created' },
  { column: 'updated_at', label: 'Last updated' },
  { column: 'due_at', label: 'Due date' },
  { column: 'title', label: 'Title' },
  { column: 'priority', label: 'Priority' },
  { column: 'status', label: 'Status' },
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
  const [isOpen, setIsOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ left: 4, top: 4 });
  const [menuTheme, setMenuTheme] = useState<Record<string, string>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const selectedColumn = COLUMN_OPTIONS.find((option) => option.column === value.column) ?? COLUMN_OPTIONS[0];
  const resolvedDirection = value.direction ?? COLUMN_DEFAULT_DIRECTION[value.column];

  useEffect(() => {
    const closeOnOutsidePointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setIsOpen(false);
    };
    document.addEventListener('mousedown', closeOnOutsidePointer);
    return () => document.removeEventListener('mousedown', closeOnOutsidePointer);
  }, []);

  function positionMenu(): void {
    const buttonBounds = buttonRef.current?.getBoundingClientRect();
    if (!buttonBounds) return;
    const measuredMenu = menuRef.current?.getBoundingClientRect();
    const menuWidth = measuredMenu?.width || Math.min(220, window.innerWidth - 8);
    const menuHeight = measuredMenu?.height || 220;
    const opensDownward = window.innerHeight - buttonBounds.bottom >= menuHeight + 4;
    setMenuPosition({
      left: Math.max(4, Math.min(buttonBounds.right - menuWidth, window.innerWidth - menuWidth - 4)),
      top: opensDownward
        ? buttonBounds.bottom + 4
        : Math.max(4, buttonBounds.top - menuHeight - 4),
    });
  }

  function open(): void {
    const computedStyle = rootRef.current ? getComputedStyle(rootRef.current) : null;
    if (computedStyle) {
      setMenuTheme(Object.fromEntries([
        '--background-primary',
        '--text-primary',
        '--text-secondary',
        '--separator-color',
        '--corner-radius-small',
        '--font-family-light',
        '--font-family-medium',
        '--font-size-status-tiny',
      ].map((property) => [property, computedStyle.getPropertyValue(property)])));
    }
    setIsOpen(true);
  }

  useLayoutEffect(() => {
    if (isOpen) positionMenu();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const reposition = () => positionMenu();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [isOpen]);

  function selectColumn(column: TodoSortColumn): void {
    onChange({ column, direction: value.column === column ? value.direction : undefined });
    setIsOpen(false);
    buttonRef.current?.focus();
  }

  function toggleDirection(): void {
    onChange({ column: value.column, direction: resolvedDirection === 'asc' ? 'desc' : 'asc' });
  }

  return (
    <div ref={rootRef} className={`todo-sort-menu${isOpen ? ' is-open' : ''}`}>
      <span className="todo-sort-menu-label">Sort To-Dos</span>
      <button
        ref={buttonRef}
        type="button"
        className="todo-sort-menu-trigger"
        aria-label="Choose the To-Do sort column"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        onClick={() => isOpen ? setIsOpen(false) : open()}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (!isOpen) open();
          }
          if (event.key === 'Escape') {
            setIsOpen(false);
            buttonRef.current?.focus();
          }
        }}
      >
        <span>{selectedColumn.label}</span>
      </button>
      <button
        type="button"
        className="todo-sort-menu-direction"
        aria-label={resolvedDirection === 'asc' ? 'Sort ascending, click to sort descending' : 'Sort descending, click to sort ascending'}
        aria-pressed={resolvedDirection === 'desc'}
        onClick={toggleDirection}
      >
        {resolvedDirection === 'asc' ? '↑' : '↓'}
      </button>
      {isOpen ? createPortal(
        <div
          ref={menuRef}
          className="todo-sort-menu-popover"
          role="listbox"
          aria-label="Sort column"
          style={{ position: 'fixed', left: menuPosition.left, top: menuPosition.top, ...menuTheme } as CSSProperties}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              setIsOpen(false);
              buttonRef.current?.focus();
            }
          }}
        >
          {COLUMN_OPTIONS.map((option) => (
            <button
              key={option.column}
              type="button"
              role="option"
              className="todo-sort-menu-option"
              aria-selected={option.column === value.column}
              onClick={() => selectColumn(option.column)}
            >
              {option.label}
            </button>
          ))}
        </div>
      , document.body) : null}
    </div>
  );
}
