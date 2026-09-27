import { useEffect, useState } from 'react';
import { ConversationOriginIcon } from '../sidebar/SidebarIcons';
import { openAgentTaskOrigin } from '../../services/bridge';
import { getTodoOriginDetail } from '../../services/api';

interface AgentTaskOriginChipProps {
  originType?: string;
  originId?: string;
}

const ORIGIN_LABELS: Record<string, string> = {
  conversation: 'From Conversation',
  todo: 'From To-Do',
  todo_workspace: 'From To-Do Workspace',
  scheduled_task: 'From Scheduled Task',
  meeting: 'From Meeting',
  validation_fixture: 'Validation fixture',
};

const MEETING_PROPOSAL_SOURCE_KIND = 'meeting_analysis_proposal';
const meetingOriginRequests = new Map<string, Promise<string | null>>();

function resolveMeetingOrigin(todoId: string): Promise<string | null> {
  const existingRequest = meetingOriginRequests.get(todoId);
  if (existingRequest) return existingRequest;

  const request = getTodoOriginDetail(todoId)
    .then(todo => {
      const meetingSource = todo.sources.find(source => source.source_kind === MEETING_PROPOSAL_SOURCE_KIND);
      const meetingId = meetingSource?.source_locator.meeting_id;
      return typeof meetingId === 'string' && meetingId.trim() ? meetingId : null;
    })
    .catch(() => null);
  meetingOriginRequests.set(todoId, request);
  return request;
}

function OriginChip({ originType, originId, label }: { originType: string; originId?: string; label: string }) {
  const canNavigate = Boolean(
    originId &&
    Object.prototype.hasOwnProperty.call(ORIGIN_LABELS, originType) &&
    originType !== 'validation_fixture',
  );
  const destinationLabel = ORIGIN_LABELS[originType]?.replace(/^From /, '').toLowerCase();

  if (!canNavigate) {
    return (
      <span className="request-display-origin-link" aria-disabled="true" title={label}>
        <ConversationOriginIcon />
        <span>{label}</span>
      </span>
    );
  }

  return (
    <button
      type="button"
      className="request-display-origin-link"
      title={`Open ${destinationLabel}`}
      aria-label={`Open ${destinationLabel}`}
      onClick={() => openAgentTaskOrigin(originType, originId!)}
    >
      <ConversationOriginIcon />
      <span>{label}</span>
    </button>
  );
}

export default function AgentTaskOriginChip({ originType, originId }: AgentTaskOriginChipProps) {
  const [meetingOriginId, setMeetingOriginId] = useState<string | null>(null);

  useEffect(() => {
    let isCurrent = true;
    setMeetingOriginId(null);
    if (originType !== 'todo' || !originId) return () => { isCurrent = false; };

    void resolveMeetingOrigin(originId).then(meetingId => {
      if (isCurrent) setMeetingOriginId(meetingId);
    });
    return () => { isCurrent = false; };
  }, [originId, originType]);

  if (!originType) return null;

  const label = ORIGIN_LABELS[originType] || `From ${originType.replace(/_/g, ' ')}`;
  return (
    <span className="request-display-origin-links">
      <OriginChip originType={originType} originId={originId} label={label} />
      {meetingOriginId && (
        <OriginChip
          originType="meeting"
          originId={meetingOriginId}
          label="Originally from Meeting"
        />
      )}
    </span>
  );
}
