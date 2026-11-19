import { StopCircleIcon } from './CircleControlIcons';
import './stop-action.css';

interface StopActionProps {
  isStopping: boolean;
  onStop: () => void;
  className?: string;
  title?: string;
  /** `icon` draws the Notetaker's stop icon instead of the word. The accessible name stays "Stop" or "Stopping". */
  variant?: 'text' | 'icon';
}

function classNames(variant: 'text' | 'icon', className?: string): string {
  const base = variant === 'icon' ? 'basil-stop-action basil-stop-action--icon' : 'basil-stop-action';
  return className ? `${base} ${className}` : base;
}

export function StopAction({ isStopping, onStop, className, title, variant = 'text' }: StopActionProps) {
  const label = isStopping ? 'Stopping' : 'Stop';

  return (
    <button
      type="button"
      className={classNames(variant, className)}
      onClick={onStop}
      disabled={isStopping}
      title={title || label}
      aria-label={label}
    >
      {variant === 'icon' ? <StopCircleIcon /> : label}
    </button>
  );
}
