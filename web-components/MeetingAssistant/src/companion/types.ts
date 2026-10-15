export type CompanionMode = 'active' | 'passive';
export type CompanionCapacity = 'ok' | 'deferred' | 'paused';
export type CompanionItemKind = 'insight' | 'suggestion' | 'answer' | 'context_note' | 'proposal';
export type CompanionProposalAction = 'todo' | 'agent_task' | 'assistant_session';
export type CompanionAutoProposalAction = 'todo' | 'agent_task';
export type CompanionProposalAuthority = 'review' | 'watch';
export type CompanionProposalState = 'proposed' | 'started' | 'handed_off' | 'dismissed' | 'failed';
export type CompanionProposalMode = 'suggestion_only' | 'auto_execute';
export type CompanionProposalDecision = 'approve' | 'dismiss';
export type CompanionFeedbackAction = 'dismissed' | 'pinned' | 'unpinned' | 'copied' | 'useful' | 'not_useful';
export type CompanionRootKind = 'folder' | 'file';
export type CompanionTimelineKind = 'item' | 'retrieval' | 'feedback' | 'chat' | 'watch' | 'source' | 'status' | 'error' | 'proposal';

export interface FileCitation {
  path: string;
  line_start: number;
  line_end: number;
  excerpt: string;
}

export interface TranscriptRange {
  start: number;
  end: number;
  turn_ids: string[];
}

/** A follow-up action the investigator proposed and what became of it; updated only by `proposal` timeline events. */
export interface CompanionProposalInfo {
  proposal_id: string;
  action: CompanionProposalAction;
  title: string;
  instruction: string;
  authority: CompanionProposalAuthority;
  state: CompanionProposalState;
  todo_id: string | null;
  agent_task_id: string | null;
  error: string | null;
  auto_started: boolean;
}

/** The answer to `POST .../items/{id}/proposal`; a failed start is a normal answer with `state: 'failed'`. */
export interface CompanionProposalResult {
  state: CompanionProposalState;
  title: string;
  instruction: string;
  todo_id: string | null;
  agent_task_id: string | null;
  error: string | null;
}

export interface CompanionItem {
  id: string;
  kind: CompanionItemKind;
  text: string;
  confidence: number;
  citations: FileCitation[];
  no_source: boolean;
  transcript_range: TranscriptRange;
  trigger: string;
  watch_id: string | null;
  truncated: boolean;
  pinned: boolean;
  dismissed: boolean;
  /** Milliseconds from the Companion deciding to speak until the item appeared; absent on items saved before it was recorded. */
  latency_ms?: number | null;
  /** True for an item that came from an investigation; absent on items saved before investigations existed. */
  researched?: boolean;
  investigation_id?: string | null;
  evidence_count?: number;
  /** Present only on `kind: 'proposal'` items. */
  proposal?: CompanionProposalInfo | null;
}

export interface TimelineEvent {
  id: string;
  seq: number;
  kind: CompanionTimelineKind;
  meeting_time: number;
  wall_time: string;
  payload: Record<string, unknown>;
}

export interface CompanionRoot {
  id: string;
  path: string;
  display_name: string;
  kind: CompanionRootKind;
  attached_at: number;
  detached_at: number | null;
}

export interface CompanionWatch {
  id: string;
  topic: string;
  instruction: string;
  keywords: string[];
  created_at: number;
  active: boolean;
  last_triggered_at: number | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  meeting_time: number;
  truncated: boolean;
  status: 'complete' | 'error';
}

export interface CompanionStatus {
  live: boolean;
  enabled: boolean;
  mode: CompanionMode;
  model_id: string | null;
  /** What the user asked the Companion to concentrate on in this meeting; empty when nothing was set. */
  focus: string;
  capacity: CompanionCapacity;
  capacity_reason: string | null;
  latest_meeting_time: number;
  transcription_lag_seconds: number;
  evaluating: boolean;
  /** How many investigations are running right now. */
  investigating: number;
  /** The per-meeting switch that lets the Companion research questions. */
  investigate: boolean;
}

export interface CompanionSnapshot {
  meeting_id: string;
  session_key: string;
  status: CompanionStatus;
  roots: CompanionRoot[];
  items: CompanionItem[];
  watches: CompanionWatch[];
  chat: ChatMessage[];
  retrievals: TimelineEvent[];
  last_seq: number;
}

export interface CompanionGlobalSettings {
  auto_enable: boolean;
  default_mode: CompanionMode;
  screen_share_note_dismissed: boolean;
  /** Focus typed before a recording starts; the next auto-enabled meeting takes it and the backend then clears it. */
  next_focus: string;
  /** `auto_execute` lets a watch the user created start approved kinds of action without a click; the default never does. */
  proposal_mode: CompanionProposalMode;
  /** Which kinds of action the Companion may propose at all. */
  proposal_capabilities: CompanionProposalAction[];
  /** Which kinds may start by themselves when `proposal_mode` is `auto_execute`; never contains `assistant_session`. */
  auto_execute_capabilities: CompanionAutoProposalAction[];
}

/** One frame from the shared `/ws` bus; only frames whose `event_type` starts with `meeting_companion_` are read. */
export interface CompanionSocketEvent {
  event_type: string;
  session_key?: string;
  meeting_ids?: string[];
  [key: string]: unknown;
}

export const EMPTY_COMPANION_STATUS: CompanionStatus = {
  live: false,
  enabled: false,
  mode: 'active',
  model_id: null,
  focus: '',
  capacity: 'ok',
  capacity_reason: null,
  latest_meeting_time: 0,
  transcription_lag_seconds: 0,
  evaluating: false,
  investigating: 0,
  investigate: true,
};
