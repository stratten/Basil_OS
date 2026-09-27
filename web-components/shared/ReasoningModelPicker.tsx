import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import './rich-text-followup.css';

// Same asset + `currentColor` mask technique as `TranscriptionWidget`'s
// `TranscriptionSymbol` chevronDown glyph (shared/assets/native-symbols/ is
// common to both). A plain text '⌄' character previously stood in here, but
// its glyph varies by font/baseline and can render ambiguously (even
// upside-down-looking) instead of as a clean, unambiguous down-chevron.
const chevronDownUrl = new URL('./assets/native-symbols/assistant-chevron-down.png', import.meta.url).href;

function ChevronDownGlyph({ size = 9 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        flex: '0 0 auto',
        width: size,
        height: size,
        backgroundColor: 'currentColor',
        WebkitMaskImage: `url("${chevronDownUrl}")`,
        maskImage: `url("${chevronDownUrl}")`,
        WebkitMaskPosition: 'center',
        maskPosition: 'center',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskSize: 'contain',
        maskSize: 'contain',
      }}
    />
  );
}

export interface SharedReasoningModel {
  id: string;
  name: string;
  display_name?: string;
  category: 'local' | 'api' | 'custom';
}

interface ReasoningModelPickerProps {
  models: SharedReasoningModel[];
  selectedModelId?: string;
  disabled: boolean;
  onModelChange: (modelId?: string) => void;
  /** When supplied, opens a native menu anchored to the shared trigger instead of rendering the in-WebView portal menu. */
  onRequestNativeMenu?: (anchorRect: DOMRect) => void;
  ariaLabel?: string;
  placeholder?: string;
  /** Renders a spinner in place of the trigger label/chevron while true; trigger stays non-interactive regardless of `disabled`. Existing consumers omit this (defaults to false) and see zero behavior change. */
  busy?: boolean;
  /** 'default' (unchanged, existing consumers' behavior) renders the full `<span>{label}</span><span>⌄</span>` trigger. 'miniChevron' renders a bare 14x14 chevron-only trigger for hover-revealed compact placements. Menu, grouping, positioning, and keyboard handling are identical in both variants. */
  variant?: 'default' | 'miniChevron';
}

const GROUPS: Array<{ category: SharedReasoningModel['category']; label: string }> = [
  { category: 'local', label: 'Local Models' },
  { category: 'api', label: 'API Models' },
  { category: 'custom', label: 'Custom Models' },
];

export default function ReasoningModelPicker({
  models,
  selectedModelId,
  disabled,
  onModelChange,
  onRequestNativeMenu,
  ariaLabel = 'Reasoning model',
  placeholder,
  busy = false,
  variant = 'default',
}: ReasoningModelPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ left: 4, top: 4 });
  const [menuTheme, setMenuTheme] = useState<Record<string, string>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selected = models.find((model) => model.id === selectedModelId);
  const label = selected?.display_name || selected?.name || (models.length ? (placeholder ?? 'Choose model') : 'No models available');
  const orderedModels = GROUPS.flatMap(({ category }) => models.filter((model) => model.category === category));

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
    const menuWidth = measuredMenu?.width || Math.min(320, window.innerWidth - 8);
    const menuHeight = measuredMenu?.height || 260;
    const opensDownward = window.innerHeight - buttonBounds.bottom >= menuHeight + 4;
    setMenuPosition({
      left: Math.max(4, Math.min(buttonBounds.left + ((buttonBounds.width - menuWidth) / 2), window.innerWidth - menuWidth - 4)),
      top: opensDownward
        ? buttonBounds.bottom + 4
        : Math.max(4, buttonBounds.top - menuHeight - 4),
    });
  }

  function open(): void {
    if (onRequestNativeMenu && buttonRef.current) {
      onRequestNativeMenu(buttonRef.current.getBoundingClientRect());
      return;
    }
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

  function select(modelId: string): void {
    onModelChange(modelId);
    setIsOpen(false);
    buttonRef.current?.focus();
  }

  const triggerClassName = [
    'rich-text-model-picker-trigger',
    variant === 'miniChevron' ? 'rich-text-model-picker-trigger--mini-chevron' : null,
  ].filter(Boolean).join(' ');

  return (
    <div ref={rootRef} className={`rich-text-model-picker${isOpen ? ' is-open' : ''}`}>
      <button
        ref={buttonRef}
        type="button"
        className={triggerClassName}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        disabled={busy || disabled || models.length === 0}
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
        {variant === 'miniChevron' ? (
          busy ? (
            <span className="rich-text-model-picker-trigger__spinner" aria-hidden="true" />
          ) : (
            <ChevronDownGlyph size={9} />
          )
        ) : busy ? (
          <>
            <span className="rich-text-model-picker-trigger__spinner" aria-hidden="true" />
            <span>Switching…</span>
          </>
        ) : (
          <>
            <span>{label}</span>
            <ChevronDownGlyph size={9} />
          </>
        )}
      </button>
      {isOpen ? createPortal(
        <div
          ref={menuRef}
          className="rich-text-model-picker-menu"
          role="listbox"
          aria-label="Reasoning models"
          style={{ position: 'fixed', left: menuPosition.left, top: menuPosition.top, ...menuTheme } as CSSProperties}
          onKeyDown={(event) => {
            const currentIndex = Math.max(0, orderedModels.findIndex((model) => model.id === selectedModelId));
            if (event.key === 'Escape') {
              event.preventDefault();
              setIsOpen(false);
              buttonRef.current?.focus();
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              const offset = event.key === 'ArrowDown' ? 1 : -1;
              const nextIndex = (currentIndex + offset + orderedModels.length) % orderedModels.length;
              optionRefs.current[nextIndex]?.focus();
            }
          }}
        >
          {GROUPS.map(({ category, label: groupLabel }) => {
            const groupModels = models.filter((model) => model.category === category);
            if (groupModels.length === 0) return null;
            return (
              <div key={category} className="rich-text-model-picker-group" role="group" aria-label={groupLabel}>
                <span>{groupLabel}</span>
                {groupModels.map((model) => (
                  <button
                    ref={(node) => { optionRefs.current[orderedModels.findIndex((candidate) => candidate.id === model.id)] = node; }}
                    key={model.id}
                    type="button"
                    role="option"
                    aria-selected={model.id === selectedModelId}
                    onClick={() => select(model.id)}
                  >
                    {model.display_name || model.name}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      , document.body) : null}
    </div>
  );
}
