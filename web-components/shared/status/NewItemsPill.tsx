interface NewItemsPillProps {
  /** How many items arrived while the reader was looking elsewhere. The pill renders nothing at zero. */
  count: number;
  onClick: () => void;
  className?: string;
}

/** The "N new" control that floats above the bottom edge of a stream the reader has scrolled away from. Clicking it jumps to the first unseen item. It sits inside a `position: relative` wrapper that also holds the scroll region. */
export default function NewItemsPill({ count, onClick, className }: NewItemsPillProps) {
  if (!(count > 0)) return null;
  const label = `${count} new`;
  return (
    <button
      type="button"
      className={['basil-new-items-pill', 'basil-presence-enter', className].filter(Boolean).join(' ')}
      aria-label={count === 1 ? 'Jump to 1 new item' : `Jump to ${count} new items`}
      onClick={onClick}
    >
      <span aria-hidden="true" className="basil-new-items-pill__arrow">↓</span>
      {label}
    </button>
  );
}
