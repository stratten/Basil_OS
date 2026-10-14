export type CompanionMode = 'active' | 'passive';
export type CompanionCapacity = 'ok' | 'deferred' | 'paused';
export type CompanionItemKind = 'insight' | 'suggestion' | 'answer' | 'context_note';
export type CompanionFeedbackAction = 'dismissed' | 'pinned' | 'unpinned' | 'copied' | 'useful' | 'not_useful';
export type CompanionRootKind = 'folder' | 'file';
export type CompanionTimelineKind = 'item' | 'retrieval' | 'feedback' | 'chat' | 'watch' | 'source' | 'status' | 'error';

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
};
