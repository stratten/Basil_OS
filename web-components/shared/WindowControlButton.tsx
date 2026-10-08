import './window-control-button.css';

export type WindowControlKind = 'close' | 'minimize' | 'collapse';

export interface WindowControlButtonProps {
  kind: WindowControlKind;
  label: string;
  onClick: () => void;
  className?: string;
  collapsed?: boolean;
  pressed?: boolean;
}

/** One circular window-control glyph button (close, minimize, or collapse chevron). The host keeps its own button class for size, spacing, hover, and focus styling; the glyph, circle fill, and chevron rotation are shared. `pressed` adds aria-pressed only when a host asks for it. The handler is called without arguments. */
export function WindowControlButton({ kind, label, onClick, className, collapsed = false, pressed }: WindowControlButtonProps) {
  return (
    <button type="button" className={className} onClick={() => onClick()} aria-label={label} aria-pressed={pressed}>
      <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
        <circle className="basil-window-control-circle" cx="11" cy="11" r="10" />
        {kind === 'close' ? (
          <>
            <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
          </>
        ) : null}
        {kind === 'minimize' ? (
          <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
        ) : null}
        {kind === 'collapse' ? (
          <path
            className={`basil-window-control-chevron${collapsed ? ' is-collapsed' : ''}`}
            d="M7 9l4 4 4-4"
            fill="none"
            stroke="var(--secondary)"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
      </svg>
    </button>
  );
}
