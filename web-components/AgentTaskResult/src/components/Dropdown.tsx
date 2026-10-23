import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

/**
 * Reusable dropdown that visually matches the widget's existing model
 * selector (.model-selector-trigger / .model-selector-dropdown). We use this
 * instead of a native <select> anywhere we want consistent styling, because
 * native <select> renders the macOS WebKit gradient pill and a system popup
 * panel that does not match the rest of the result widget's UI.
 *
 * The popup direction (up vs. down) is computed at open time based on the
 * trigger's position within the viewport so it never gets clipped.
 */

export interface DropdownOption<T extends string> {
  value: T;
  label: string;
  // Optional secondary text rendered to the right of the option label.
  hint?: string;
}

interface Props<T extends string> {
  value: T;
  options: DropdownOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  disabled?: boolean;
  searchable?: boolean;
  // Inline style on the trigger button so callers can size it within a row.
  triggerStyle?: React.CSSProperties;
  // Optional explicit aria-label for accessibility when label is icon-only.
  ariaLabel?: string;
}

export default function Dropdown<T extends string>({
  value,
  options,
  onChange,
  placeholder,
  disabled,
  searchable,
  triggerStyle,
  ariaLabel,
}: Props<T>) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [direction, setDirection] = useState<'up' | 'down'>('down');
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const selected = useMemo(
    () => options.find(opt => opt.value === value) ?? null,
    [options, value]
  );

  const visibleOptions = useMemo(() => {
    if (!searchable || !filter.trim()) return options;
    const needle = filter.trim().toLowerCase();
    return options.filter(
      opt =>
        opt.label.toLowerCase().includes(needle) ||
        opt.value.toLowerCase().includes(needle) ||
        (opt.hint ?? '').toLowerCase().includes(needle)
    );
  }, [options, filter, searchable]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  // Decide whether the popup should render upward or downward based on
  // available viewport space at the moment the dropdown opens. Prevents
  // the popup from getting clipped at the bottom of the WKWebView.
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    setDirection(spaceBelow < 220 && spaceAbove > spaceBelow ? 'up' : 'down');
    if (searchable) {
      setFilter('');
      setTimeout(() => searchRef.current?.focus(), 0);
    }
  }, [open, searchable]);

  const handleSelect = (next: T) => {
    onChange(next);
    setOpen(false);
  };

  const popupStyle: React.CSSProperties =
    direction === 'down'
      ? { top: 'calc(100% + 4px)', bottom: 'auto' }
      : { bottom: 'calc(100% + 4px)', top: 'auto' };

  return (
    <div
      ref={wrapperRef}
      className="model-selector-wrapper"
      style={{ minWidth: 0, overflow: 'visible' }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="model-selector-trigger"
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        style={{ width: '100%', justifyContent: 'space-between', ...triggerStyle }}
      >
        <span className="model-selector-label" style={{ maxWidth: 'none', flex: 1, textAlign: 'left' }}>
          {selected ? selected.label : placeholder ?? 'Select…'}
        </span>
        <span aria-hidden style={{ fontSize: 9, opacity: 0.7, marginLeft: 6 }}>▾</span>
      </button>
      {open && (
        <div
          className="model-selector-dropdown"
          role="listbox"
          style={{ ...popupStyle, left: 0, right: 0, minWidth: '100%', maxWidth: 'none' }}
        >
          {searchable && (
            <div style={{ padding: 6, borderBottom: '1px solid var(--separator-color)' }}>
              <input
                ref={searchRef}
                className="sidebar-search-input"
                type="text"
                placeholder="Search…"
                value={filter}
                onChange={e => setFilter(e.target.value)}
                onClick={e => e.stopPropagation()}
              />
            </div>
          )}
          {visibleOptions.length === 0 ? (
            <div style={{ padding: '8px 12px', color: 'var(--text-secondary)', fontSize: 12 }}>
              No matches
            </div>
          ) : (
            visibleOptions.map(opt => (
              <button
                key={opt.value}
                type="button"
                role="option"
                aria-selected={opt.value === value}
                className={`model-selector-option${opt.value === value ? ' selected' : ''}`}
                onClick={() => handleSelect(opt.value)}
              >
                <span className="model-option-name">{opt.label}</span>
                {opt.hint && <span className="model-option-provider">{opt.hint}</span>}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
