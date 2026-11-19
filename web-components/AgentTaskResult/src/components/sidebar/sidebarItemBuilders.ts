import type { MouseEvent } from 'react';
import type { AgentState, AgentTaskListItem, ScheduledAgentTask } from '../../types';
import type { ScheduledRunNowOutcome } from '../../services/scheduledRunNow';
import type { AgentTaskRowProps } from './AgentTaskRow';
import { plainSidebarText, stripStepMarkers, truncateTitle } from './sidebarUtils';

/** The backend grades `completed_with_warnings` as success, but the turn label shows it as a partial result, so the sidebar icon follows the label. */
export function sidebarResultSeverity(resultSeverity: string | undefined, outcome: string | undefined): string | undefined {
  return outcome?.trim().toLowerCase() === 'completed_with_warnings' ? 'warning' : resultSeverity;
}

/** The unselected-row preview for a task waiting on the user. Token, command input, approval, and a question each get their own line. */
export function sidebarAttentionPreview(agent: Pick<
  AgentState,
  'showApprovalPrompt' | 'showTokenConnectPrompt' | 'showCheckpointPrompt' | 'approvalRequests' | 'status'
>): string | undefined {
  if (agent.showTokenConnectPrompt) return 'Token needed';
  if (agent.showApprovalPrompt) {
    const requests = agent.approvalRequests ?? [];
    if (requests.length > 0 && requests.every(request => request.execution_type === 'command_input')) {
      return 'Input needed';
    }
    return 'Approval needed';
  }
  if (agent.showCheckpointPrompt || agent.status === 'awaitingInput') return 'Your turn';
  return undefined;
}

export function isActiveStatus(s: string): boolean {
  return ['processing', 'routing', 'capturing', 'awaitingInput', 'paused'].includes(s);
}

// Backend statuses of a chain that is still running or waiting; the backend refuses to archive these.
const UNARCHIVABLE_BACKEND_STATUSES = ['capturing', 'routing', 'processing', 'awaiting_user_input', 'needs_clarification', 'paused'];

interface BuildHistoryItemsArgs {
  allAgents: AgentState[];
  history: AgentTaskListItem[];
  activeIds: Set<string>;
  // Root task ids currently open in a detached window. Those windows own their
  // task's interactive surface, so the main-window sidebar suppresses the
  // approval/awaiting signal for them (state is preserved, not cleared).
  detachedRoots: Set<string>;
  selectedId?: string | null;
  viewedAgentTaskId?: string | null;
  viewedRootId?: string | null;
  selectAgent: (agentTaskId: string) => void;
  handleSelectHistoryId: (id: string) => void;
  requestDeleteId: (id: string) => void;
  // Archives (or, with archiveLabel 'Unarchive', restores) a row's chain; only rows that are not running offer it.
  archiveAgentTask?: (id: string) => void;
  archiveLabel?: 'Archive' | 'Unarchive';
  detachAgentTask: (rootTaskId: string) => void;
  cancelAgentTask: (agentTaskId: string) => void;
  getAgentRootTaskId: (agentTaskId: string) => string | undefined;
  openContextMenuForId: (event: MouseEvent, id: string) => void;
  // When true, history rows of the same active/inactive-ness keep the
  // relative order they were passed in (relies on Array.prototype.sort's
  // guaranteed stability) instead of being re-sorted by timestamp. The
  // caller sets this while a search query is active so it doesn't discard
  // the backend's relevance-tiered search order. Defaults to false so
  // normal chronological browsing is unaffected.
  preserveHistoryOrder?: boolean;
  // Due time (ISO) of each chain root's soonest scheduled follow-up check.
  pendingFollowUps?: Readonly<Record<string, string>>;
}

/** The label of the clock badge for a task that a schedule started. Falls back to a generic label when the API didn't fill in the schedule's title (older rows, or scheduled agent tasks that have since been deleted). */
function scheduledRunLabel(item: Pick<AgentTaskListItem, 'scheduled_agent_task_title'>): string {
  return plainSidebarText(item.scheduled_agent_task_title || '') || 'Scheduled task';
}

export function buildHistoryItems({
  allAgents,
  history,
  activeIds,
  detachedRoots,
  selectedId,
  viewedAgentTaskId,
  viewedRootId,
  selectAgent,
  handleSelectHistoryId,
  requestDeleteId,
  archiveAgentTask,
  archiveLabel,
  detachAgentTask,
  cancelAgentTask,
  getAgentRootTaskId,
  openContextMenuForId,
  preserveHistoryOrder = false,
  pendingFollowUps = {},
}: BuildHistoryItemsArgs): AgentTaskRowProps[] {
  // A task a schedule started keeps its badge for as long as it exists. A task that is open in this window, or that has had turns here, is shown from the live store instead of the history list, and the live state has no record of where the task came from, so the backend's history entry for the same task supplies it.
  const scheduledHistoryById = new Map(history.filter(item => item.is_scheduled_run).map(item => [item.id, item]));
  const historyItems: AgentTaskRowProps[] = [
    ...allAgents.map((agent): AgentTaskRowProps => {
      // While this task's root is open in a detached window, that window owns
      // its interactive surface. Don't surface an approval/awaiting signal in
      // the main-window sidebar for it: clear needsApproval and present an
      // awaiting-input status as plain 'processing' (it is actively handled in
      // the pop-out). The store's real state is untouched, so if the detached
      // window closes while genuinely still awaiting, the badge returns.
      const rootId = agent.rootTaskId || agent.agentTaskId;
      const isDetachedElsewhere = detachedRoots.has(rootId);
      const rowStatus = agent.isCanceled
        ? 'canceled'
        : isDetachedElsewhere && agent.status === 'awaitingInput'
          ? 'processing'
          : agent.status;
      const active = isActiveStatus(rowStatus);
      const attentionPreview = isDetachedElsewhere ? undefined : sidebarAttentionPreview(agent);
      const scheduledSource = scheduledHistoryById.get(rootId) ?? scheduledHistoryById.get(agent.agentTaskId);
      return {
        id: agent.agentTaskId,
        // The generated title always wins once the task has one, as it does for the same task in the history list. Until then the row shows the first prompt that is in memory, then the newest one.
        title: agent.taskTitle
          ? truncateTitle(plainSidebarText(agent.taskTitle))
          : agent.agentTaskHistory.length > 0 && agent.agentTaskHistory[0].agentTaskText
            ? truncateTitle(plainSidebarText(agent.agentTaskHistory[0].agentTaskText))
            : agent.originalPrompt
              ? truncateTitle(plainSidebarText(agent.originalPrompt))
              : 'Processing...',
        status: rowStatus,
        resultSeverity: sidebarResultSeverity(agent.resultSeverity, agent.outcome),
        currentStep: active ? (agent.currentStep || rowStatus) : undefined,
        timestamp: agent.timestamp || undefined,
        fileCount: 0,
        followUpCount: agent.agentTaskHistory.length,
        hasUnreadResult: agent.hasUnreadResult || false,
        needsApproval: Boolean(attentionPreview),
        attentionPreview,
        isSelected: agent.agentTaskId === selectedId,
        onSelect: selectAgent,
        onDetach: detachAgentTask,
        onCancel: active ? cancelAgentTask : undefined,
        onRequestDelete: !active ? requestDeleteId : undefined,
        onArchive: !active ? archiveAgentTask : undefined,
        archiveLabel,
        onContextMenu: openContextMenuForId,
        scheduledRunSourceTitle: scheduledSource ? scheduledRunLabel(scheduledSource) : undefined,
        originSourceLabel: agent.originType === 'conversation'
          ? 'From Conversation'
          : undefined,
        nextFollowUpAt: pendingFollowUps[rootId] ?? pendingFollowUps[agent.agentTaskId],
        checklistRootId: rootId,
      };
    }),
    ...history
      .filter(item => {
        if (activeIds.has(item.id)) return false;
        for (const a of allAgents) {
          if (a.rootTaskId === item.id) return false;
        }
        return true;
      })
      .map((item): AgentTaskRowProps => ({
        id: item.id,
        title: item.title
          ? plainSidebarText(item.title)
          : truncateTitle(plainSidebarText(item.original_prompt)),
        status: item.status,
        resultSeverity: sidebarResultSeverity(item.result_severity, item.outcome),
        preview: item.result_preview
          ? plainSidebarText(stripStepMarkers(item.result_preview))
          : undefined,
        timestamp: item.timestamp,
        fileCount: item.file_count,
        followUpCount: item.follow_up_count,
        hasUnreadResult: false,
        isSelected: item.id === selectedId
          || (!!selectedId && getAgentRootTaskId(selectedId) === item.id)
          || item.id === viewedAgentTaskId
          || item.id === viewedRootId,
        onSelect: handleSelectHistoryId,
        onDetach: detachAgentTask,
        onRequestDelete: requestDeleteId,
        onArchive: UNARCHIVABLE_BACKEND_STATUSES.includes(item.status) ? undefined : archiveAgentTask,
        archiveLabel,
        onContextMenu: openContextMenuForId,
        // Surface the scheduled-run provenance to the row itself so it can
        // render the clock badge inline next to the title.
        scheduledRunSourceTitle: item.is_scheduled_run ? scheduledRunLabel(item) : undefined,
        originSourceLabel: item.origin_type === 'conversation'
          ? 'From Conversation'
          : undefined,
        nextFollowUpAt: pendingFollowUps[item.id],
        checklistRootId: item.id,
        checklistDone: item.checklist_done ?? 0,
        checklistTotal: item.checklist_total ?? 0,
      })),
  ];

  historyItems.sort((a, b) => {
    const aActive = isActiveStatus(a.status);
    const bActive = isActiveStatus(b.status);
    if (aActive !== bActive) return aActive ? -1 : 1;
    if (preserveHistoryOrder) return 0;
    if (a.timestamp && b.timestamp)
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    if (!a.timestamp && b.timestamp) return -1;
    if (a.timestamp && !b.timestamp) return 1;
    return 0;
  });

  return historyItems;
}

interface BuildScheduledItemsArgs {
  scheduled: ScheduledAgentTask[];
  selectedScheduledAgentTaskId?: string | null;
  onViewScheduledAgentTask: (scheduledAgentTaskId: string) => void;
  deleteScheduledAgentTask: (scheduledAgentTaskId: string) => void;
  /** Activates or deactivates a schedule from its status dot. Without it the dot is a plain indicator. */
  toggleScheduledAgentTask?: (scheduledAgentTaskId: string, nextActive: boolean) => void;
  /** Starts one run of a schedule now, whether or not it is active. Without it the rows have no Run now button. */
  runScheduledAgentTask?: (scheduledAgentTaskId: string) => Promise<ScheduledRunNowOutcome>;
}

export function buildScheduledItems({
  scheduled,
  selectedScheduledAgentTaskId,
  onViewScheduledAgentTask,
  deleteScheduledAgentTask,
  toggleScheduledAgentTask,
  runScheduledAgentTask,
}: BuildScheduledItemsArgs): AgentTaskRowProps[] {
  const scheduledItems: AgentTaskRowProps[] = scheduled.map((item): AgentTaskRowProps => {
    const kindLabel = item.schedule_type === 'one_time' ? 'One-time' : 'Recurring';
    const scheduleText = !item.is_active
      ? `Inactive • ${kindLabel}`
      : item.schedule_type === 'one_time'
        ? `One-time • ${item.next_run_at ? new Date(item.next_run_at).toLocaleString() : 'unscheduled'}`
        : `Recurring • ${item.next_run_at ? `next ${new Date(item.next_run_at).toLocaleString()}` : 'no upcoming run'}`;
    // Health-state mapping for the StatusIcon. The previous mapping
    // (``is_active ? 'completed' : 'failed'``) was wrong: a successful
    // one-time schedule deactivates itself on completion (the right
    // semantic — a one-time AgentTask shouldn't keep firing forever), and
    // would then render as a red X here even though it ran fine. The
    // active-vs-inactive distinction is already conveyed by the schedule
    // preview text below, so this icon should only signal genuine
    // health: red iff the last execution actually failed, green
    // otherwise. Whether the schedule is still firing is shown separately by
    // scheduleActive (a green dot or a hollow ring) and the preview text.
    const rowStatus = item.last_status === 'failed' ? 'failed' : 'completed';
    return {
      id: item.id,
      title: plainSidebarText(item.title || '') || 'Scheduled task',
      status: rowStatus,
      preview: scheduleText,
      timestamp: item.updated_at,
      fileCount: item.run_count || 0,
      followUpCount: 0,
      hasUnreadResult: false,
      isSelected: selectedScheduledAgentTaskId === item.id,
      onSelect: onViewScheduledAgentTask,
      onRequestDelete: deleteScheduledAgentTask,
      scheduleActive: item.is_active,
      onToggleSchedule: toggleScheduledAgentTask,
      onRunSchedule: runScheduledAgentTask,
      deleteConfirmLabel: 'Delete this schedule?',
    };
  });

  scheduledItems.sort((a, b) => {
    if (a.timestamp && b.timestamp) {
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    }
    return 0;
  });

  return scheduledItems;
}
