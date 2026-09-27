import type { ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

/**
 * ``processingRgb`` has no equivalent in the canonical `@shared/webTheme`
 * contract -- it is this panel's own derived helper for the CSS
 * ``rgba(var(--processing-rgb), alpha)`` pulse-halo effect, published
 * alongside the canonical hex tokens by
 * ``ScheduledRunMiniPanelWebView.colorToRgbTriplet``. The former
 * ``primaryRgb`` companion field was retired in favor of
 * ``color-mix(in srgb, var(--primary) X%, transparent)``, which needs no
 * RGB-triplet plumbing (see the appearance-presets-and-border-tokenization
 * plan, Companion 01).
 */
export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string;
  primary: string;
  processingRgb?: string;
  secondary: string;
  textPrimary: string;
};

export interface FontConfig {
  fontFamily: string;
  fontFamilyMedium: string;
  fontFamilyBold: string;
}

/**
 * Currently in-flight scheduled run, joined to its parent scheduled agent task for label.
 * Mirrors the Pydantic ``ScheduledActiveRunItem`` defined in
 * ``backend/src/api/routes/agent_task_routes.py``.
 *
 * The mini panel asks the backend for these on cold open so it can re-render
 * any runs that were already in flight before the panel was shown / re-shown.
 */
export interface ActiveRunItem {
  run_id: string;
  scheduled_agent_task_id: string;
  agent_task_id?: string | null;
  scheduled_for: string;
  started_at?: string | null;
  title: string;
  agent_task_text: string;
}

export interface InitMessage {
  wsUrl: string;
  port: number;
  theme: ThemeConfig;
  fonts: FontConfig;
  /**
   * Optional pre-hydrated rows. Swift may pass these directly when it
   * already has them; otherwise the panel will fetch
   * ``GET /api/v1/agent-task-runs/active`` on mount.
   */
  hydrate?: ActiveRunItem[];
}

/**
 * One row in the panel. Tracks one in-flight (or just-completed) scheduled run.
 *
 *  * ``runId``        — primary key from the backend (one per execution).
 *  * ``agentTaskId``    — the agent_task_id once the backend allocates it.
 *                       Used by the click-through into the result widget.
 *  * ``status``       — drives the status dot color and is set from WS events.
 *  * ``currentStep``  — last seen step text from ``agent_progress_update``,
 *                       displayed under the title in muted type.
 */
export interface MiniPanelRow {
  runId: string;
  scheduledAgentTaskId: string;
  agentTaskId?: string;
  title: string;
  currentStep: string;
  status: 'running' | 'completed' | 'failed';
  startedAt: number;
}

export type SwiftMessage =
  | { type: 'openAgentTaskInResultWidget'; agentTaskId: string; runId: string }
  | { type: 'dismissRow'; runId: string }
  | { type: 'dismissPanel' }
  /**
   * Ask the host NSPanel to minimize itself into the Dock. Handled
   * Swift-side by ``ScheduledRunMiniPanelWebView`` forwarding to
   * ``ScheduledRunMiniPanelWindowController.panel.miniaturize(nil)``.
   * Distinct from ``dismissPanel`` (which destroys the panel) and
   * ``panelEmpty`` (which is the React side telling Swift it
   * auto-orders out because there's nothing to show): minimize keeps
   * the panel state alive in the Dock so the user can restore it.
   */
  | { type: 'minimizePanel' }
  | { type: 'panelEmpty' }
  | { type: 'requestResize'; width: number; height: number };

export type WSEvent = {
  event_type: string;
  [key: string]: unknown;
};
