import { openDetachedAgentTask } from '../services/bridge';
import { plainMarkdownText } from '../../../shared/text/plainMarkdownText';

interface DetachedTaskPlaceholderProps {
  rootTaskId: string;
  taskTitle?: string;
}

export default function DetachedTaskPlaceholder({
  rootTaskId,
  taskTitle,
}: DetachedTaskPlaceholderProps) {
  const plainTaskTitle = plainMarkdownText(taskTitle);
  return (
    <div className="content-area">
      <div className="empty-state" style={{ flex: 1 }}>
        {plainTaskTitle && <span>{plainTaskTitle}</span>}
        <span>This task is open in a separate window.</span>
        <button className="action-btn primary" onClick={() => openDetachedAgentTask(rootTaskId)}>
          Bring window to front
        </button>
      </div>
    </div>
  );
}
