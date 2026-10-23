interface EmptyStateProps {
  title: string;
  message: string;
}

export function EmptyState({ title, message }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-title">{title}</span>
      <span>{message}</span>
    </div>
  );
}
