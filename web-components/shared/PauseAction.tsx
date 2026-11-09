import { PauseCircleIcon, PlayCircleIcon } from './CircleControlIcons';
import './pause-action.css';

interface PauseActionProps {
  /** `paused` shows the play icon and resumes; `running` shows the pause icon and pauses. */
  state: 'running' | 'paused';
  /** A pause has been requested and takes effect after the current step, so the button waits. */
  isPending?: boolean;
  onPause: () => void;
  onResume: () => void;
  className?: string;
}

export function PauseAction({ state, isPending = false, onPause, onResume, className }: PauseActionProps) {
  const paused = state === 'paused';
  const label = paused ? 'Resume' : isPending ? 'Pausing after this step' : 'Pause';
  const title = paused ? 'Resume the task' : isPending ? 'Pausing after this step' : 'Pause after the current step';

  return (
    <button
      type="button"
      className={className ? `basil-pause-action ${className}` : 'basil-pause-action'}
      onClick={paused ? onResume : onPause}
      disabled={!paused && isPending}
      title={title}
      aria-label={label}
    >
      {paused ? <PlayCircleIcon /> : <PauseCircleIcon />}
    </button>
  );
}
