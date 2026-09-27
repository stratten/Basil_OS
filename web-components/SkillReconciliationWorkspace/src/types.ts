// Theme/font payloads injected by the Swift host (AestheticWebPayload).
import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';
export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string;
  primary: string;
  secondary: string;
  textPrimary: string;
};
export type FontConfig = SharedFontConfig & {
  fontFamily: string;
  fontFamilyMedium: string;
  fontFamilyBold: string;
};

// Injected at document-start by the native host.
export interface ReconciliationConfig {
  apiBaseUrl: string;
  wsUrl: string;
  port: number;
  theme?: ThemeConfig;
  fonts?: FontConfig;
}

// Generic websocket envelope from the shared /ws bus.
export interface WSEvent {
  event_type: string;
  [key: string]: unknown;
}

export type ActionKind =
  | 'merge_candidates'
  | 'enhance_saved_skill'
  | 'duplicate_of_saved_skill'
  | 'keep_new'
  | 'delete_saved_skill';

export type ActionDecision = 'pending' | 'accepted' | 'rejected';

export type SessionStatus =
  | 'analyzing'
  | 'ready'
  | 'committing'
  | 'committed'
  | 'discarded';

export interface ProposedAction {
  id: string;
  kind: ActionKind;
  source_candidate_ids: string[];
  target_skill_slug: string | null;
  rationale: string;
  merged_title: string | null;
  merged_when_to_use: string | null;
  merged_triggers: string[];
  merged_procedure_markdown: string | null;
  merged_expected_result: string | null;
  merged_source_task_ids: string[];
  decision: ActionDecision;
  user_edited: ActionEditFields | null;
}

export interface ActionEditFields {
  title?: string | null;
  when_to_use?: string | null;
  triggers?: string[] | null;
  procedure_markdown?: string | null;
  expected_result?: string | null;
  source_task_ids?: string[] | null;
}

export interface SkillCandidateSnapshot {
  id: string;
  title: string;
  when_to_use: string;
  triggers: string[];
  procedure_markdown: string;
  expected_result: string;
  source_task_ids: string[];
  status: string;
  observation_count: number;
}

export interface SavedSkillSnapshot {
  slug: string;
  title: string;
  when_to_use: string;
  triggers: string[];
  source_task_ids: string[];
  observation_count: number;
  version: number;
  body: string;
}

export interface SessionSnapshot {
  captured_at: string;
  pending_candidates: SkillCandidateSnapshot[];
  saved_skills: SavedSkillSnapshot[];
  min_observations: number;
}

export interface ProgressState {
  phase: string;
  processed: number;
  total: number;
}

export interface CommitReport {
  session_id: string;
  committed_at: string;
  applied: Array<Record<string, unknown>>;
  skipped: Array<{ action_id: string; kind: string; reason: string }>;
  accepted_total: number;
}

export interface ReconciliationSession {
  id: string;
  status: SessionStatus;
  created_at: string;
  updated_at: string;
  snapshot: SessionSnapshot;
  actions: ProposedAction[];
  progress: ProgressState;
  errors: string[];
  commit_report: CommitReport | null;
}
