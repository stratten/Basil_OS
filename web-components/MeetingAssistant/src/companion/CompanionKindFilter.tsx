import { COMPANION_KIND_FILTERS, type CompanionKindFilter as KindFilter } from './companionStreamSelectors';

interface CompanionKindFilterProps {
  value: KindFilter;
  counts: Record<KindFilter, number>;
  onChange: (next: KindFilter) => void;
}

/** One button per kind of note above the stream. The active one is filled. A kind with nothing yet stays visible but is disabled, so the set of choices never shifts; the current choice never disables, so it can always be left. */
export default function CompanionKindFilter({ value, counts, onChange }: CompanionKindFilterProps) {
  return (
    <div className="companion-kind-filter" role="group" aria-label="Show">
      {COMPANION_KIND_FILTERS.map((filter) => {
        const count = counts[filter.value];
        const active = value === filter.value;
        return (
          <button
            key={filter.value}
            type="button"
            className={`companion-kind-filter-button${active ? ' is-active' : ''}`}
            aria-pressed={active}
            disabled={!active && count === 0}
            onClick={() => onChange(filter.value)}
          >
            {filter.label}
            {filter.value !== 'all' && <span className="companion-kind-filter-count">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
