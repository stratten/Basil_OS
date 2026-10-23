export function ProgressMessage({
  show,
  message,
}: {
  show: boolean;
  message: string | null;
}) {
  if (!show) return null;
  return (
    <div className="assistant-session-progress-message">
      {message ?? '\u00a0'}
    </div>
  );
}
