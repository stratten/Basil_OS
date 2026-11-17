import { useId } from 'react';
import ScheduledField from './ScheduledField';

interface Props {
  title: string;
  onTitleChange: (value: string) => void;
  taskText: string;
  onTaskTextChange: (value: string) => void;
}

/** The labeled Title and Task rows that open the create and edit forms. The task is the text the person reads and edits most, so it is set at the form's full text size. */
export default function ScheduledTextFields({ title, onTitleChange, taskText, onTaskTextChange }: Props) {
  const titleId = useId();
  const taskId = useId();
  return (
    <>
      <ScheduledField label="Title" htmlFor={titleId}>
        <input
          id={titleId}
          className="scheduled-input"
          placeholder="Title (optional — derived from the task if left blank)"
          value={title}
          onChange={e => onTitleChange(e.target.value)}
        />
      </ScheduledField>
      <ScheduledField label="Task" htmlFor={taskId}>
        <textarea
          id={taskId}
          className="scheduled-input scheduled-input--text"
          placeholder="Task text"
          value={taskText}
          onChange={e => onTaskTextChange(e.target.value)}
        />
      </ScheduledField>
    </>
  );
}
