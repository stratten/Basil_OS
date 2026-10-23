import { consideredCounterText } from './companionEvaluations';

interface CompanionConsideredBarProps {
  total: number;
  spoke: number;
  shown: boolean;
  onToggle: (next: boolean) => void;
}

/** The always-visible answer to "is it working?": how many times the Companion checked and how often it spoke, with a switch for the per-check rows. */
export default function CompanionConsideredBar({ total, spoke, shown, onToggle }: CompanionConsideredBarProps) {
  return (
    <div className="companion-considered-bar">
      <span className="companion-considered-counter">{consideredCounterText(total, spoke)}</span>
      <button type="button" className="meeting-history-load-more-button" aria-pressed={shown} onClick={() => onToggle(!shown)}>
        {shown ? 'Hide what it considered' : 'Show what it considered'}
      </button>
    </div>
  );
}
