import { openDetachedAgentTask } from '../services/bridge';

interface DetachedTaskPlaceholderProps {
  rootTaskId: string;
  taskTitle?: string;
}

export default function DetachedTaskPlaceholder({
  rootTaskId,
  taskTitle,
}: DetachedTaskPlaceholderProps) {
  return (
    <div className="content-area">
      <div className="empty-state" style={{ flex: 1 }}>
        {taskTitle && <span>{taskTitle}</span>}
        <span>This task is open in a separate window.</span>
        <button className="action-btn primary" onClick={() => openDetachedAgentTask(rootTaskId)}>
          Bring window to front
        </button>
      </div>
    </div>
  );
}
