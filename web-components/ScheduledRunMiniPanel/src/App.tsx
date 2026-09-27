import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { InitMessage, MiniPanelRow, ActiveRunItem, WSEvent } from './types';
import {
  registerInitHandler,
  registerThemeHandler,
  openAgentTaskInResultWidget,
  dismissRow as bridgeDismissRow,
  dismissPanel as bridgeDismissPanel,
  minimizePanel as bridgeMinimizePanel,
  notifyPanelEmpty,
  requestResize,
} from './services/bridge';
import { wsManager } from './services/websocket';
import * as api from './services/api';
import ScheduledRunRow from './components/ScheduledRunRow';
import { applyHostTheme } from './app/themeBootstrap';

const ROW_HEIGHT = 52;
const HEADER_HEIGHT = 32;
const ROWS_BOTTOM_GUTTER = 4;
const PANEL_WIDTH = 320;
const MAX_VISIBLE_ROWS = 4;
const COMPLETED_ROW_LINGER_MS = 4000;
const FAILED_ROW_LINGER_MS = 8000;

// Mirrors the fallback stack in panel.css :root defaults. Any sanitized
// Swift-supplied family is prepended to this so a single misrecognized name
// never causes the browser to fall back to Times.
const SYSTEM_FONT_FALLBACK = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';

/**
 * Translate the Swift-supplied font name into a CSS-safe `font-family` value.
 *
 * Swift's ``AestheticSystem.Typography.preferredFontName`` returns the
 * macOS *PostScript* name (e.g. ``"Helvetica-Light"``, ``"SFProText-Regular"``).
 * Those are valid `NSFont` identifiers but they are NOT valid CSS
 * `font-family` tokens — CSS only knows the base family name (``"Helvetica"``,
 * ``"SF Pro Text"``). When we wrote the raw PostScript name into the
 * `--font-family-*` CSS variables the browser couldn't resolve it and fell
 * all the way back to its default serif (Times), which is what made the
 * panel render in the wrong font even though Swift was sending a name.
 *
 * Strategy:
 *   1. Strip common weight/style suffixes from the PostScript name to
 *      recover the base family.
 *   2. Quote if it contains whitespace.
 *   3. Always append the system fallback stack so a partial miss
 *      (unassistantSession custom font, typo, future renames) still renders
 *      readable text in the system UI font instead of Times.
 *
 * This intentionally swallows the Swift name entirely if it's empty
 * — the all-system fallback is always the right answer in that case.
 */
function toCssFontFamily(rawName: string | null | undefined): string {
  const trimmed = (rawName ?? '').trim();
  if (!trimmed) {
    return SYSTEM_FONT_FALLBACK;
  }
  const base = trimmed
    .replace(
      /-(?:UltraLight|Thin|ExtraLight|Light|Regular|Book|Medium|Semibold|SemiBold|DemiBold|Bold|ExtraBold|Heavy|Black|Italic|Oblique|Condensed|Compressed|Expanded|Extended|Display|Text|MT)$/i,
      ''
    )
    .trim();
  const needsQuotes = /[\s'"]/.test(base);
  const formatted = needsQuotes ? `"${base.replace(/"/g, '\\"')}"` : base;
  return `${formatted}, ${SYSTEM_FONT_FALLBACK}`;
}

/**
 * Floating mini panel that shows currently-executing scheduled agent tasks.
 *
 * Lifecycle:
 *  1. Swift hosts this in a non-activating NSPanel and calls
 *     ``window.basilMiniPanel.onInit({ wsUrl, port, theme, fonts, hydrate })``
 *     once the WKWebView finishes loading.
 *  2. On init we open the WS, hydrate from
 *     ``GET /api/v1/agent-task-runs/active`` if Swift didn't pre-pass rows,
 *     and start listening for ``scheduled_agent_task_run_started``,
 *     ``agent_progress_update``, and ``scheduled_agent_task_run_completed``.
 *  3. Each row tracks one ``run_id``. ``run_started`` adds. ``progress_update``
 *     updates the step label. ``run_completed`` flips status (and sets a
 *     timer that auto-dismisses the row a few seconds later so the user
 *     sees the final state before it disappears).
 *  4. When the row count hits zero we tell Swift via ``panelEmpty`` so the
 *     host NSPanel can order itself out without waiting for a user dismiss.
 *
 * NOT a goal: persistence. The backend is the source of truth for which
 * runs are active; if this panel is closed, restarted, or hot-reloaded
 * mid-run, the next mount will repopulate from ``runs/active``.
 */
export default function App() {
  const [rows, setRows] = useState<MiniPanelRow[]>([]);
  const [initialized, setInitialized] = useState(false);
  const lingerTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const emptyNotifyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tracks whether we've ever shown a row, so we don't fire panelEmpty on
  // the initial empty render before any runs have started.
  const everHadRows = useRef(false);

  const upsertRow = useCallback((row: MiniPanelRow) => {
    setRows(prev => {
      const idx = prev.findIndex(r => r.runId === row.runId);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = { ...next[idx], ...row };
        return next;
      }
      return [...prev, row];
    });
  }, []);

  const updateRow = useCallback((runId: string, patch: Partial<MiniPanelRow>) => {
    setRows(prev => prev.map(r => (r.runId === runId ? { ...r, ...patch } : r)));
  }, []);

  const removeRow = useCallback((runId: string) => {
    const t = lingerTimers.current.get(runId);
    if (t) {
      clearTimeout(t);
      lingerTimers.current.delete(runId);
    }
    setRows(prev => prev.filter(r => r.runId !== runId));
  }, []);

  // Schedule auto-dismissal once a row has resolved. Failed runs stick around
  // a bit longer than completed ones so the user has a chance to read them.
  const scheduleLingerRemoval = useCallback((runId: string, status: 'completed' | 'failed') => {
    const existing = lingerTimers.current.get(runId);
    if (existing) clearTimeout(existing);
    const delay = status === 'failed' ? FAILED_ROW_LINGER_MS : COMPLETED_ROW_LINGER_MS;
    const t = setTimeout(() => {
      lingerTimers.current.delete(runId);
      removeRow(runId);
    }, delay);
    lingerTimers.current.set(runId, t);
  }, [removeRow]);

  const hydrateFromBackend = useCallback(async () => {
    try {
      const items = await api.fetchActiveScheduledRuns();
      setRows(prev => {
        const byRun = new Map(prev.map(r => [r.runId, r]));
        for (const it of items) {
          if (byRun.has(it.run_id)) continue;
          byRun.set(it.run_id, activeItemToRow(it));
        }
        return Array.from(byRun.values());
      });
    } catch (err) {
      console.warn('[MiniPanel] Failed to hydrate active runs:', err);
    }
  }, []);

  const handleInit = useCallback((config: InitMessage) => {
    api.setBaseUrl(config.port);
    if (config.theme) {
      applyHostTheme(config.theme);
      const root = document.documentElement;
      if (config.theme.processingRgb) {
        root.style.setProperty('--processing-rgb', config.theme.processingRgb);
      }
    }
    if (config.fonts) {
      const root = document.documentElement;
      root.style.setProperty('--font-family-light', toCssFontFamily(config.fonts.fontFamily));
      root.style.setProperty('--font-family-medium', toCssFontFamily(config.fonts.fontFamilyMedium));
      root.style.setProperty('--font-family-bold', toCssFontFamily(config.fonts.fontFamilyBold));
    }
    // Pre-hydrated rows from Swift (best-effort; backend is canonical).
    if (config.hydrate && config.hydrate.length > 0) {
      setRows(prev => {
        const byRun = new Map(prev.map(r => [r.runId, r]));
        for (const it of config.hydrate!) {
          byRun.set(it.run_id, activeItemToRow(it));
        }
        return Array.from(byRun.values());
      });
    }
    void hydrateFromBackend();
    wsManager.onConnect(() => {
      void hydrateFromBackend();
    });
    wsManager.connect(config.wsUrl);
    setInitialized(true);
  }, [hydrateFromBackend]);

  useEffect(() => {
    registerInitHandler(handleInit);
    registerThemeHandler((theme, fonts) => {
      applyHostTheme(theme);
      const root = document.documentElement;
      if (theme.processingRgb) {
        root.style.setProperty('--processing-rgb', theme.processingRgb);
      }
      root.style.setProperty('--font-family-light', toCssFontFamily(fonts.fontFamily));
      root.style.setProperty('--font-family-medium', toCssFontFamily(fonts.fontFamilyMedium));
      root.style.setProperty('--font-family-bold', toCssFontFamily(fonts.fontFamilyBold));
    });
  }, [handleInit]);

  useEffect(() => {
    if (!initialized) return;
    const unsubscribe = wsManager.subscribe((event: WSEvent) => {
      const eventType = event.event_type;
      if (eventType === 'scheduled_agent_task_run_started') {
        const runId = event.run_id as string | undefined;
        const scheduledAgentTaskId = event.scheduled_agent_task_id as string | undefined;
        if (!runId || !scheduledAgentTaskId) return;
        upsertRow({
          runId,
          scheduledAgentTaskId,
          agentTaskId: (event.agent_task_id as string | undefined) ?? undefined,
          title: (event.title as string | undefined) ?? 'Scheduled agent task',
          currentStep: 'Starting…',
          status: 'running',
          startedAt: Date.now(),
        });
        return;
      }
      if (eventType === 'agent_progress_update') {
        // Generic progress events still use agent_task_id; for scheduled
        // runs, that value is the executed AgentTask row id we stored as
        // agentTaskId. The backend doesn't tag progress events with
        // run_id, so we match by that executed task id.
        //
        // ``workflow_status_notifier.send_agent_progress_update`` emits
        // ``message`` as the primary payload field (with optional
        // ``details``). The previous order tried ``step_text`` first --
        // that field is never set by the backend, so progress updates
        // were silently no-opping. Read ``message`` first; fall back to
        // ``details`` or ``tool_name`` for edge cases.
        const agentTaskId = event.agent_task_id as string | undefined;
        if (!agentTaskId) return;
        const stepText =
          (event.message as string | undefined) ??
          (event.details as string | undefined) ??
          (event.tool_name as string | undefined);
        if (!stepText) return;
        setRows(prev => prev.map(r => (r.agentTaskId === agentTaskId ? { ...r, currentStep: stepText } : r)));
        return;
      }
      if (eventType === 'agent_task_step_detail') {
        // Emitted by
        // ``workflow_status_notifier.send_step_detail_update`` -- this
        // is the richest "what is the agent currently doing" stream
        // available, surfacing tool inputs / partial outputs as the
        // step runs. Payload shape: { entry: { summary, content,
        // body, ...}, delta?, agent_task_id, ... }. ``agent_task_id``
        // is stamped on the OUTER message by
        // ``WorkflowStatusNotifier._prepare_frontend_notification``
        // (workflow_status_notifier.py:62-70), NOT into the ``entry``
        // dict that ``send_step_detail_update`` forwards verbatim.
        // The previous shape read ``entry.agent_task_id`` and so
        // silently dropped every step-detail event because that
        // field is never set inside entry. Match on the outer
        // ``event.agent_task_id`` and pull the first non-empty of
        // summary -> content -> body off the entry for the row label.
        const entry = event.entry as { [key: string]: unknown } | undefined;
        if (!entry) return;
        const agentTaskId = event.agent_task_id as string | undefined;
        if (!agentTaskId) return;
        const stepText =
          (entry.summary as string | undefined) ??
          (entry.content as string | undefined) ??
          (entry.body as string | undefined);
        if (!stepText) return;
        setRows(prev => prev.map(r => (r.agentTaskId === agentTaskId ? { ...r, currentStep: stepText } : r)));
        return;
      }
      if (eventType === 'step_progress_update') {
        // Emitted by ``workflow_status_notifier.send_step_update``.
        // Payload (own fields): { todo_id, step_id, status,
        // result_summary? }. ``agent_task_id`` is NOT part of the
        // payload that ``send_step_update`` constructs, but the
        // notifier's ``_prepare_frontend_notification`` stamps the
        // owning ``agent_task_id`` onto the outer message before
        // broadcast (workflow_status_notifier.py:62-70), so when the
        // notifier is task-scoped (which it is for scheduled runs)
        // we DO see it on the wire.
        //
        // Prefer the explicit match by ``event.agent_task_id`` when
        // it is present -- that is the correct attribution and works
        // for any future multi-concurrent-run scenario. Fall back to
        // the "most recently started running row" heuristic only when
        // the field is absent, which covers older / non-task-scoped
        // notifier emissions and the brief self-heal window where a
        // row may not have its agentTaskId hydrated yet.
        const resultSummary = event.result_summary as string | undefined;
        if (!resultSummary) return;
        const eventAgentTaskId = event.agent_task_id as string | undefined;
        setRows(prev => {
          if (eventAgentTaskId) {
            let matched = false;
            const next = prev.map(r => {
              if (r.agentTaskId === eventAgentTaskId) {
                matched = true;
                return { ...r, currentStep: resultSummary };
              }
              return r;
            });
            if (matched) return next;
            // Fall through to the heuristic if the explicit match
            // didn't find a row (e.g. self-heal hasn't completed
            // yet and no row has this agentTaskId set).
          }
          // Fallback: update the most-recently-started running row
          // with a populated agentTaskId. There is almost always
          // exactly one of these for scheduled runs.
          const running = prev
            .map((r, idx) => ({ r, idx }))
            .filter(({ r }) => r.status === 'running' && r.agentTaskId)
            .sort((a, b) => b.r.startedAt - a.r.startedAt);
          if (running.length === 0) return prev;
          const targetIdx = running[0].idx;
          const next = [...prev];
          next[targetIdx] = { ...next[targetIdx], currentStep: resultSummary };
          return next;
        });
        return;
      }
      if (eventType === 'scheduled_agent_task_run_completed') {
        const runId = event.run_id as string | undefined;
        if (!runId) return;
        const backendStatus = event.status as string | undefined;
        const status: 'completed' | 'failed' = backendStatus === 'completed' ? 'completed' : 'failed';
        updateRow(runId, {
          status,
          currentStep: status === 'completed' ? 'Completed' : 'Failed',
          agentTaskId: (event.agent_task_id as string | undefined) ?? undefined,
        });
        scheduleLingerRemoval(runId, status);
        return;
      }
    });
    return () => {
      unsubscribe();
    };
  }, [initialized, upsertRow, updateRow, scheduleLingerRemoval]);

  // Self-heal rows whose ``agentTaskId`` is still undefined after
  // hydration. There are two cases this catches:
  //
  //   1. Cold-open mid-run: ``orderFrontIfHidden()`` creates the
  //      NSPanel + WKWebView lazily in response to the
  //      ``scheduled_agent_task_run_started`` broadcast, so by the
  //      time this React app boots and its WS finishes the handshake,
  //      the started event has already shipped. Fallback hydration
  //      from ``/agent-task-runs/active`` is the only source for that
  //      row -- but the backing DB column is NULL during the run for
  //      most of its duration (see the FK comment in
  //      scheduled_run_execution.py), so the row arrives with
  //      ``agentTaskId === undefined`` and every match-by-agent_task_id
  //      handler below silently no-ops.
  //   2. Brief race between the run row flipping to ``status=running``
  //      and process_agent_task_direct returning (when scheduled_run_
  //      execution.py finally writes ``agent_task_id``). Sub-second
  //      normally; can be longer if the orchestrator is contended.
  //
  // Strategy: when at least one row still has no ``agentTaskId``,
  // refetch ``/active`` at ~2 s and again at ~6 s and patch any rows
  // whose runId matches. Two retries are enough -- if both come back
  // NULL we stop, because at that point the run is genuinely stuck
  // and polling adds noise rather than information.
  //
  // Rows that already have an ``agentTaskId`` are never rewritten, so
  // a concurrent ``run_started`` event populating the field will not
  // be clobbered.
  useEffect(() => {
    if (!initialized) return;
    const hasPending = rows.some(r => !r.agentTaskId && r.status === 'running');
    if (!hasPending) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const reconcile = async () => {
      try {
        const items = await api.fetchActiveScheduledRuns();
        const byRun = new Map(items.map(it => [it.run_id, it]));
        setRows(prev => prev.map(r => {
          if (r.agentTaskId) return r;
          const remote = byRun.get(r.runId);
          if (!remote || !remote.agent_task_id) return r;
          return { ...r, agentTaskId: remote.agent_task_id };
        }));
      } catch (err) {
        console.warn('[MiniPanel] self-heal refetch failed:', err);
      }
    };
    timers.push(setTimeout(reconcile, 2000));
    timers.push(setTimeout(reconcile, 6000));
    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, [initialized, rows]);

  // Tell Swift to resize the host window to fit visible rows so it never
  // shows a slab of empty whitespace under the last row.
  useLayoutEffect(() => {
    if (!initialized) return;
    const visibleRowCount = Math.min(rows.length, MAX_VISIBLE_ROWS);
    const overflow = rows.length > MAX_VISIBLE_ROWS;
    const contentHeight = HEADER_HEIGHT + visibleRowCount * ROW_HEIGHT + ROWS_BOTTOM_GUTTER + (overflow ? 4 : 0);
    requestResize(PANEL_WIDTH, Math.max(HEADER_HEIGHT + ROW_HEIGHT, contentHeight));
  }, [rows.length, initialized]);

  // Coalesced "panel empty" notification. Avoids spamming Swift if rows
  // briefly drop to zero between events; if a new row appears within
  // ~250ms we cancel the empty notify.
  useEffect(() => {
    if (rows.length > 0) {
      everHadRows.current = true;
      if (emptyNotifyTimer.current) {
        clearTimeout(emptyNotifyTimer.current);
        emptyNotifyTimer.current = null;
      }
      return;
    }
    if (!everHadRows.current) return;
    if (emptyNotifyTimer.current) clearTimeout(emptyNotifyTimer.current);
    emptyNotifyTimer.current = setTimeout(() => {
      emptyNotifyTimer.current = null;
      notifyPanelEmpty();
    }, 250);
  }, [rows.length]);

  useEffect(() => {
    return () => {
      for (const t of lingerTimers.current.values()) clearTimeout(t);
      lingerTimers.current.clear();
      if (emptyNotifyTimer.current) clearTimeout(emptyNotifyTimer.current);
      wsManager.disconnect();
    };
  }, []);

  const openScheduledRun = useCallback((agentTaskId: string, runId: string) => {
    openAgentTaskInResultWidget(agentTaskId, runId);
  }, []);

  const dismissScheduledRun = useCallback((runId: string) => {
    bridgeDismissRow(runId);
    removeRow(runId);
  }, [removeRow]);

  return (
    <div className="basil-webkit-window-frame">
      <div className="mini-panel basil-webkit-window-surface" role="region" aria-label="Scheduled agent task runs">
      <div className="mini-panel-header">
        <div className="mini-panel-header-title">
          <span>Scheduled runs</span>
          {rows.length > 0 && <span className="mini-panel-header-count">{rows.length}</span>}
        </div>
        <div className="mini-panel-header-actions">
          {/*
            Minimize button mirrors the standard window-control vocabulary:
            ``−`` (U+2212 MINUS SIGN) glyph for "minimize to Dock",
            ``×`` for "dismiss". Both buttons share the same hover /
            focus chrome via .mini-panel-dismiss so they read as a
            single control group. The minimize action goes through the
            bridge -> Swift -> NSPanel.miniaturize(nil) rather than any
            CSS / web minimization because the panel itself lives in a
            non-activating NSPanel; only AppKit can park it in the Dock.
          */}
          <button
            type="button"
            className="mini-panel-dismiss"
            onClick={() => bridgeMinimizePanel()}
            aria-label="Minimize panel"
            title="Minimize"
          >
            −
          </button>
          <button
            type="button"
            className="mini-panel-dismiss"
            onClick={() => bridgeDismissPanel()}
            aria-label="Dismiss panel"
            title="Hide"
          >
            ×
          </button>
        </div>
      </div>
      <div className="mini-panel-rows">
        {rows.map((row) => (
          <ScheduledRunRow
            key={row.runId}
            row={row}
            onOpen={openScheduledRun}
            onDismiss={dismissScheduledRun}
          />
        ))}
      </div>
      </div>
    </div>
  );
}

function activeItemToRow(item: ActiveRunItem): MiniPanelRow {
  return {
    runId: item.run_id,
    scheduledAgentTaskId: item.scheduled_agent_task_id,
    agentTaskId: item.agent_task_id ?? undefined,
    title: item.title,
    currentStep: 'Running…',
    status: 'running',
    startedAt: item.started_at ? Date.parse(item.started_at) : Date.now(),
  };
}
