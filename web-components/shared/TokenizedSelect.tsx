import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from 'react';
import { createPortal } from 'react-dom';
import './tokenized-select.css';

export interface TokenizedSelectOption<T extends string | number> {
  value: T;
  label: string;
  disabled?: boolean;
  group?: string;
}

interface TokenizedSelectProps<T extends string | number> {
  value: T;
  options: readonly TokenizedSelectOption<T>[];
  onValueChange: (value: T) => void;
  disabled?: boolean;
  busy?: boolean;
  ariaLabel: string;
  className?: string;
  placeholder?: string;
}

const THEME_PROPERTIES = [
  '--background-primary',
  '--background-secondary',
  '--background-tertiary',
  '--text-primary',
  '--text-secondary',
  '--primary',
  '--secondary',
  '--separator-color',
  '--corner-radius-small',
  '--shadow-medium',
  '--font-family-light',
  '--font-family-medium',
  '--font-size-status-tiny',
] as const;

export default function TokenizedSelect<T extends string | number>({
  value,
  options,
  onValueChange,
  disabled = false,
  busy = false,
  ariaLabel,
  className,
  placeholder = 'Select…',
}: TokenizedSelectProps<T>) {
  const [isOpen, setIsOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ left: 4, top: 4, width: 180 });
  const [menuTheme, setMenuTheme] = useState<Record<string, string>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const enabledOptions = useMemo(() => options.filter((option) => !option.disabled), [options]);
  const selectedOption = options.find((option) => option.value === value);
  const groupedOptions = useMemo(() => {
    const groups = new Map<string, TokenizedSelectOption<T>[]>();
    for (const option of options) {
      const label = option.group ?? '';
      const group = groups.get(label) ?? [];
      group.push(option);
      groups.set(label, group);
    }
    return [...groups.entries()];
  }, [options]);

  function closeAndFocusTrigger(): void {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  function positionMenu(): void {
    const triggerBounds = triggerRef.current?.getBoundingClientRect();
    if (!triggerBounds) return;
    const measuredMenu = menuRef.current?.getBoundingClientRect();
    const viewportPadding = 4;
    const width = Math.min(
      Math.max(triggerBounds.width, measuredMenu?.width ?? 220),
      window.innerWidth - viewportPadding * 2,
    );
    const height = measuredMenu?.height ?? 260;
    const opensDownward = window.innerHeight - triggerBounds.bottom >= height + viewportPadding
      || triggerBounds.top < height + viewportPadding;
    setMenuPosition({
      left: Math.max(viewportPadding, Math.min(triggerBounds.left, window.innerWidth - width - viewportPadding)),
      top: opensDownward
        ? Math.min(triggerBounds.bottom + 4, window.innerHeight - height - viewportPadding)
        : Math.max(viewportPadding, triggerBounds.top - height - 4),
      width,
    });
  }

  function open(): void {
    if (disabled || busy || enabledOptions.length === 0) return;
    const computedStyle = rootRef.current ? getComputedStyle(rootRef.current) : null;
    if (computedStyle) {
      setMenuTheme(Object.fromEntries(
        THEME_PROPERTIES.map((property) => [property, computedStyle.getPropertyValue(property)]),
      ));
    }
    setIsOpen(true);
  }

  function selectOption(option: TokenizedSelectOption<T>): void {
    if (option.disabled) return;
    onValueChange(option.value);
    closeAndFocusTrigger();
  }

  function focusOption(offset: number): void {
    const currentIndex = Math.max(0, enabledOptions.findIndex((option) => option.value === value));
    const nextIndex = (currentIndex + offset + enabledOptions.length) % enabledOptions.length;
    optionRefs.current[nextIndex]?.focus();
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    if (event.key === 'Escape' && isOpen) {
      event.preventDefault();
      closeAndFocusTrigger();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!isOpen) {
        open();
        return;
      }
      focusOption(event.key === 'ArrowUp' ? -1 : 1);
    }
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeAndFocusTrigger();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusOption(1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusOption(-1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      optionRefs.current[0]?.focus();
    } else if (event.key === 'End') {
      event.preventDefault();
      optionRefs.current[enabledOptions.length - 1]?.focus();
    }
  }

  useLayoutEffect(() => {
    if (isOpen) positionMenu();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;
    function closeOnOutsidePointer(event: MouseEvent): void {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setIsOpen(false);
    }
    function reposition(): void {
      positionMenu();
    }
    document.addEventListener('mousedown', closeOnOutsidePointer);
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      document.removeEventListener('mousedown', closeOnOutsidePointer);
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [isOpen]);

  let enabledIndex = 0;
  return (
    <div ref={rootRef} className="tokenized-select">
      <button
        ref={triggerRef}
        type="button"
        className={['tokenized-select__trigger', className].filter(Boolean).join(' ')}
        data-value={String(value)}
        data-option-count={options.length}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        disabled={disabled || busy || enabledOptions.length === 0}
        onClick={() => (isOpen ? setIsOpen(false) : open())}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="tokenized-select__label">{busy ? 'Updating…' : selectedOption?.label ?? placeholder}</span>
        <span className="tokenized-select__chevron" aria-hidden="true">⌄</span>
      </button>
      {isOpen ? createPortal(
        <div
          ref={menuRef}
          className="tokenized-select__menu"
          role="listbox"
          aria-label={ariaLabel}
          tabIndex={-1}
          style={{ position: 'fixed', left: menuPosition.left, top: menuPosition.top, width: menuPosition.width, ...menuTheme } as CSSProperties}
          onKeyDown={handleMenuKeyDown}
        >
          {groupedOptions.map(([groupLabel, group]) => (
            <div key={groupLabel || '__ungrouped'} className="tokenized-select__group" role={groupLabel ? 'group' : undefined} aria-label={groupLabel || undefined}>
              {groupLabel ? <span className="tokenized-select__group-label">{groupLabel}</span> : null}
              {group.map((option) => {
                const optionIndex = option.disabled ? -1 : enabledIndex++;
                return (
                  <button
                    key={String(option.value)}
                    ref={(node) => {
                      if (optionIndex >= 0) optionRefs.current[optionIndex] = node;
                    }}
                    type="button"
                    role="option"
                    aria-selected={option.value === value}
                    disabled={option.disabled}
                    className={`tokenized-select__option${option.value === value ? ' is-selected' : ''}`}
                    onClick={() => selectOption(option)}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          ))}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
