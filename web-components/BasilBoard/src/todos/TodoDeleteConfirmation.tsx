interface TodoDeleteConfirmationProps {
  isDeleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  className?: string;
}

export default function TodoDeleteConfirmation({
  isDeleting,
  onConfirm,
  onCancel,
  className = '',
}: TodoDeleteConfirmationProps) {
  return (
    <section className={`todo-delete-confirmation${className ? ` ${className}` : ''}`} role="alert">
      <p>Delete this To-Do permanently? Its provenance, attachments, and work history will be removed. Existing Agent Tasks will remain available.</p>
      <div>
        <button type="button" className="todo-detail-action-delete" disabled={isDeleting} onClick={onConfirm}>
          {isDeleting ? 'Deleting…' : 'Delete permanently'}
        </button>
        <button type="button" disabled={isDeleting} onClick={onCancel}>Keep To-Do</button>
      </div>
    </section>
  );
}
