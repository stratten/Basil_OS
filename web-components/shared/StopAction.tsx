import './stop-action.css';

interface StopActionProps {
  isStopping: boolean;
  onStop: () => void;
  className?: string;
  title?: string;
}

function classNames(className?: string): string {
  return className ? `basil-stop-action ${className}` : 'basil-stop-action';
}

export function StopAction({ isStopping, onStop, className, title }: StopActionProps) {
  const label = isStopping ? 'Stopping' : 'Stop';

  return (
    <button
      type="button"
      className={classNames(className)}
      onClick={onStop}
      disabled={isStopping}
      title={title || label}
      aria-label={label}
    >
      {label}
    </button>
  );
}
