import type { MouseEvent } from 'react';
import type { AgentState, AgentTaskListItem, ScheduledAgentTask } from '../../types';
import type { AgentTaskRowProps } from './AgentTaskRow';
import { plainSidebarText, stripStepMarkers, truncateTitle } from './sidebarUtils';

export function isActiveStatus(s: string): boolean {
  return ['processing', 'routing', 'capturing', 'awaitingInput'].includes(s);
}

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
  detachAgentTask,
  cancelAgentTask,
  getAgentRootTaskId,
  openContextMenuForId,
  preserveHistoryOrder = false,
}: BuildHistoryItemsArgs): AgentTaskRowProps[] {
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
      const rowStatus = isDetachedElsewhere && agent.status === 'awaitingInput'
        ? 'processing'
        : agent.status;
      const active = isActiveStatus(rowStatus);
      return {
        id: agent.agentTaskId,
        title: agent.agentTaskHistory.length > 0 && agent.agentTaskHistory[0].agentTaskText
          ? truncateTitle(plainSidebarText(agent.agentTaskHistory[0].agentTaskText))
          : agent.originalPrompt
            ? truncateTitle(plainSidebarText(agent.originalPrompt))
            : 'Processing...',
        status: rowStatus,
        resultSeverity: agent.resultSeverity,
        currentStep: active ? (agent.currentStep || rowStatus) : undefined,
        timestamp: agent.timestamp || undefined,
        fileCount: 0,
        followUpCount: 0,
        hasUnreadResult: agent.hasUnreadResult || false,
        needsApproval: isDetachedElsewhere ? false : (agent.showApprovalPrompt || false),
        isSelected: agent.agentTaskId === selectedId,
        onSelect: selectAgent,
        onDetach: detachAgentTask,
        onCancel: active ? cancelAgentTask : undefined,
        onRequestDelete: !active ? requestDeleteId : undefined,
        onContextMenu: openContextMenuForId,
        originSourceLabel: agent.originType === 'conversation'
          ? 'From Conversation'
          : undefined,
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
        resultSeverity: item.result_severity,
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
        onContextMenu: openContextMenuForId,
        // Surface the scheduled-run provenance to the row itself so it can
        // render the clock badge inline next to the title. Falls back to a
        // generic label when the API didn't fill in scheduled_agent_task_title
        // (older rows, or scheduled agent tasks that have since been deleted).
        scheduledRunSourceTitle: item.is_scheduled_run
          ? (plainSidebarText(item.scheduled_agent_task_title || '') || 'Scheduled agent task')
          : undefined,
        originSourceLabel: item.origin_type === 'conversation'
          ? 'From Conversation'
          : undefined,
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
}

export function buildScheduledItems({
  scheduled,
  selectedScheduledAgentTaskId,
  onViewScheduledAgentTask,
  deleteScheduledAgentTask,
}: BuildScheduledItemsArgs): AgentTaskRowProps[] {
  const scheduledItems: AgentTaskRowProps[] = scheduled.map((item): AgentTaskRowProps => {
    const scheduleText = item.schedule_type === 'one_time'
      ? `One-time • ${item.next_run_at ? new Date(item.next_run_at).toLocaleString() : 'unscheduled'}`
      : `Recurring • ${item.next_run_at ? `next ${new Date(item.next_run_at).toLocaleString()}` : 'inactive'}`;
    // Health-state mapping for the StatusIcon. The previous mapping
    // (``is_active ? 'completed' : 'failed'``) was wrong: a successful
    // one-time schedule deactivates itself on completion (the right
    // semantic — a one-time AgentTask shouldn't keep firing forever), and
    // would then render as a red X here even though it ran fine. The
    // active-vs-inactive distinction is already conveyed by the schedule
    // preview text below, so this icon should only signal genuine
    // health: red iff the last execution actually failed, green
    // otherwise.
    const rowStatus = item.last_status === 'failed' ? 'failed' : 'completed';
    return {
      id: item.id,
      title: plainSidebarText(item.title || '') || 'Scheduled agent task',
      status: rowStatus,
      preview: scheduleText,
      timestamp: item.updated_at,
      fileCount: item.run_count || 0,
      followUpCount: 0,
      hasUnreadResult: false,
      isSelected: selectedScheduledAgentTaskId === item.id,
      onSelect: onViewScheduledAgentTask,
      onRequestDelete: deleteScheduledAgentTask,
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
