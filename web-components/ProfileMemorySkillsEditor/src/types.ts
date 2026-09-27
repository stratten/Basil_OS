export type ProfileEditorMode = 'memory_file' | 'skill' | 'memory_proposal' | 'skill_candidate';

import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

export type ThemeConfig = SharedThemeConfig;

export type FontConfig = SharedFontConfig;

export interface ProfileEditorConfig {
  mode: ProfileEditorMode;
  identifier: string;
  apiBaseUrl: string;
  theme?: ThemeConfig;
  fonts?: FontConfig;
}

export interface MemoryDocument {
  file_name: string;
  content: string;
  size_bytes: number;
  cap_bytes?: number | null;
}

export interface MemoryCapsResponse {
  caps: Record<string, number>;
}

export interface SkillRecord {
  slug: string;
  title: string;
  body: string;
  when_to_use: string;
  triggers: string[];
  size_bytes: number;
  cap_bytes: number;
  observation_count: number;
  version: number;
}

export interface MemoryProposal {
  id: string;
  target_file_name: string;
  entry: string;
  why?: string | null;
  confidence?: string | null;
  source: string;
  created_at: string;
  status: string;
}

export interface SkillCandidate {
  id: string;
  title: string;
  when_to_use: string;
  triggers: string[];
  procedure_markdown: string;
  expected_result: string;
  source_task_ids: string[];
  source: string;
  created_at: string;
  status: string;
  enhances_skill_slug?: string | null;
  observation_count: number;
  approved_skill_slug?: string | null;
}

export interface AgentTaskSummary {
  id: string;
  original_prompt: string;
  transcribed_prompt?: string | null;
  title?: string | null;
  status: string;
}
