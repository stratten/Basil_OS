import { request } from './api';

export type ChecklistStatus = 'pending' | 'in_progress' | 'waiting_external' | 'waiting_user' | 'done' | 'dropped';

export interface ChecklistCounts {
  total: number;
  done: number;
  open: number;
  waiting_user: number;
  waiting_external: number;
  required_open: number;
}

export interface ChecklistRef {
  id: string;
  item_id: string;
  role: string;
  ref_kind: string;
  source_system: string;
  source_scope: string;
  external_id: string;
  label: string;
  open_url: string | null;
  added_by: string | null;
  last_known_status: string | null;
  last_known_at: string | null;
}

export interface ChecklistItem {
  id: string;
  origin: string;
  title: string;
  detail: string;
  status: ChecklistStatus;
  required: boolean;
  note: string;
  waiting_on: string;
  recheck_at: string | null;
  sort_order: number;
  work_item_id: string | null;
  carried_from_item_id: string | null;
  archived_at: string | null;
  revision: number;
  created_by_task_id: string | null;
  updated_by_task_id: string | null;
  created_at: string;
  updated_at: string;
  refs: ChecklistRef[];
}

export interface ChecklistNotes {
  content: string;
  revision: number;
  updated_by: string | null;
  updated_at: string | null;
  carried_from_task_id: string | null;
}

export interface ChecklistSnapshot {
  root_task_id: string;
  exists: boolean;
  closed_at: string | null;
  items: ChecklistItem[];
  counts: ChecklistCounts;
  notes: ChecklistNotes;
  notes_max_chars: number;
}

export interface ChecklistEvent {
  id: string;
  item_id: string;
  agent_task_id: string | null;
  kind: string;
  actor: string;
  text: string;
  created_at: string;
}

export interface ChecklistCapturedAction {
  service: string;
  method: string;
  execution_state: string;
  verification_status: string;
  material_write: boolean;
  created_at: string;
}

export interface ChecklistItemLog {
  item_id: string;
  events: ChecklistEvent[];
  captured: ChecklistCapturedAction[];
}

export interface ChecklistItemDraft {
  title: string;
  detail?: string;
  required?: boolean;
  status?: ChecklistStatus;
  waiting_on?: string;
}

export interface ChecklistItemChanges {
  title?: string;
  detail?: string;
  status?: ChecklistStatus;
  required?: boolean;
  note?: string;
  waiting_on?: string;
  recheck_at?: string;
  expected_revision?: number;
}

function base(rootTaskId: string): string {
  return `/api/v1/agent-tasks/${encodeURIComponent(rootTaskId)}/checklist`;
}

/** The server answers 409 when the item or notes changed after the revision the caller held. */
export function isChecklistConflict(error: unknown): boolean {
  return error instanceof Error && /\(409\)$/.test(error.message);
}

export function getChecklist(taskId: string): Promise<ChecklistSnapshot> {
  return request('GET', base(taskId));
}

export function getChecklistItemLog(taskId: string, itemId: string): Promise<ChecklistItemLog> {
  return request('GET', `${base(taskId)}/items/${encodeURIComponent(itemId)}/log`);
}

export function addChecklistItem(taskId: string, draft: ChecklistItemDraft): Promise<{ created: boolean; duplicate: boolean; item: ChecklistItem }> {
  return request('POST', `${base(taskId)}/items`, draft);
}

export function updateChecklistItem(taskId: string, itemId: string, changes: ChecklistItemChanges): Promise<{ item: ChecklistItem; changed: boolean }> {
  return request('PATCH', `${base(taskId)}/items/${encodeURIComponent(itemId)}`, changes);
}

export function archiveChecklistItem(taskId: string, itemId: string, archived: boolean): Promise<{ item: ChecklistItem }> {
  return request('POST', `${base(taskId)}/items/${encodeURIComponent(itemId)}/archive`, { archived });
}

export function closeChecklist(taskId: string, closed: boolean): Promise<{ closed_at: string | null }> {
  return request('POST', `${base(taskId)}/close`, { closed });
}

export function saveChecklistNotes(taskId: string, content: string, expectedRevision: number): Promise<{ notes: ChecklistNotes }> {
  return request('PUT', `${base(taskId)}/notes`, { content, expected_revision: expectedRevision });
}

export function offerChecklistItemAsTodo(taskId: string, itemId: string): Promise<{ todo_id: string; status: string }> {
  return request('POST', `${base(taskId)}/items/${encodeURIComponent(itemId)}/todo`, {});
}
