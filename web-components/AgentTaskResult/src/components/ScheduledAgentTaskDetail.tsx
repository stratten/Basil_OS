import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import type { ScheduledAgentTask, ScheduledAgentTaskRun } from '../types';
import * as api from '../services/api';
import AttachedFilesDisplay from './scheduled/AttachedFilesDisplay';
import AttachedFilesEditor from './scheduled/AttachedFilesEditor';
import ScheduleControls from './scheduled/ScheduleControls';
import ScheduledRunHistoryList from './scheduled/ScheduledRunHistoryList';
import { plainMarkdownText } from '../../../shared/plainMarkdownText';
import MarkdownRenderer from './MarkdownRenderer';
import SmartPromptPanel, {
  type SmartPromptPanelHandle,
  type SmartScheduleFields,
} from './scheduled/SmartPromptPanel';
import {
  buildTimezoneOptions,
  deriveTitleFromAgentTask,
  formatTimestamp12h,
  getCurrentTimeHHMM,
  getDefaultRunAtLocal,
  getUserTimezone,
  summarizeSchedule,
} from './scheduled/scheduledAgentTaskHelpers';

interface Props {
  scheduledAgentTaskId?: string | null;
  createMode: boolean;
  onCreated?: (scheduledAgentTaskId: string) => void;
  onExitCreateMode?: () => void;
  // Fired after a successful inline edit so the parent can refresh any
  // dependent surfaces (e.g. bump the sidebar's scheduledListVersion so a
  // renamed schedule's row label updates without a manual view toggle).
  onUpdated?: (scheduledAgentTaskId: string) => void;
  // Invoked when the user clicks a run-history row that has an
  // associated agent_task_id. The parent (App) is responsible for
  // routing the selection through agentStore so the result widget
  // displays that AgentTask — same flow used by the Swift bridge's
  // ``showExistingAgentTask``.
  onViewAgentTask?: (agentTaskId: string) => void;
}

export default function ScheduledAgentTaskDetail({
  scheduledAgentTaskId,
  createMode,
  onCreated,
  onExitCreateMode,
  onUpdated,
  onViewAgentTask,
}: Props) {
  const [item, setItem] = useState<ScheduledAgentTask | null>(null);
  const [runs, setRuns] = useState<ScheduledAgentTaskRun[]>([]);
  const [loading, setLoading] = useState(false);
  // Imperative handle into the smart-prompt panel. The panel owns all of
  // its own internal state (prompt text, clarification thread, in-flight
  // flag, etc.); this ref exists only so the form's bottom "Create
  // Schedule" button can ask "did the user ever type into the smart
  // prompt textbox?" to label the create call as 'smart' or 'manual'.
  const smartPanelRef = useRef<SmartPromptPanelHandle | null>(null);

  const userTz = useMemo(() => getUserTimezone(), []);
  const timezoneOptions = useMemo(() => buildTimezoneOptions(userTz), [userTz]);

  const [title, setTitle] = useState('');
  const [agentTaskText, setAgentTaskText] = useState('');
  const [scheduleType, setScheduleType] = useState<'one_time' | 'recurring'>('recurring');
  const [timezone, setTimezone] = useState<string>(userTz);
  const [mode, setMode] = useState<'daily' | 'weekly' | 'interval'>('daily');
  const [time, setTime] = useState<string>(() => getCurrentTimeHHMM());
  const [intervalMinutes, setIntervalMinutes] = useState(60);
  const [runAt, setRunAt] = useState<string>(() => getDefaultRunAtLocal());
  // Mon=0 .. Sun=6 — default to weekdays selected.
  const [weeklyDays, setWeeklyDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [busy, setBusy] = useState(false);

  // Absolute filesystem paths the user has attached as context for this
  // scheduled agent task. Hydrated from the loaded ``item`` in the read view
  // and from the same item when entering edit mode; cleared on each
  // (re-)entry into create mode. The full list is sent on every save —
  // PATCH receives the post-edit array verbatim and replaces what the
  // backend has stored. ``AttachedFilesEditor`` owns the picker-bridge
  // wiring and append/dedupe logic; this orchestrator just holds the
  // canonical list and passes it through as a controlled value.
  const [referencePaths, setReferencePaths] = useState<string[]>([]);

  // Whether the read view is currently in inline-edit mode. Mutually
  // exclusive with createMode (createMode is owned by the parent and only
  // renders the create form path); this flag governs the read view's
  // detail panel toggling between display and edit.
  const [editing, setEditing] = useState(false);

  // Hydrate the same form-state fields used by the create flow from the
  // currently-loaded item whenever we (re-)enter edit mode. Reusing the
  // existing state slots means the schedule_config derivation memoized
  // below works identically for both create and edit, with zero schema
  // duplication. The hydration is keyed on `editing` (only on the
  // false→true transition) to avoid clobbering in-progress user edits.
  useEffect(() => {
    if (!editing || !item) return;
    setTitle(item.title || '');
    setAgentTaskText(item.agent_task_text || '');
    setScheduleType(item.schedule_type === 'one_time' ? 'one_time' : 'recurring');
    setTimezone(item.timezone || userTz);
    // Defensive copy so user-side add/remove doesn't mutate the
    // currently-displayed item until Save is clicked.
    setReferencePaths(Array.isArray(item.reference_paths) ? [...item.reference_paths] : []);
    const cfg = item.schedule_config || {};
    if (item.schedule_type === 'one_time') {
      const runAtIso = String(cfg.run_at || '');
      // datetime-local needs YYYY-MM-DDTHH:MM in *local* wall-clock time.
      // run_at is stored as the user's chosen wall-clock string already
      // (no Z suffix), so we can pass it through after light normalization.
      const m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/.exec(runAtIso);
      setRunAt(m ? m[1] : getDefaultRunAtLocal());
    } else {
      const cfgMode = String(cfg.mode || 'daily');
      if (cfgMode === 'interval') {
        setMode('interval');
        const minutes = Number(cfg.minutes);
        setIntervalMinutes(Number.isFinite(minutes) && minutes > 0 ? minutes : 60);
      } else if (cfgMode === 'weekly') {
        setMode('weekly');
        setTime(String(cfg.time || getCurrentTimeHHMM()));
        const days = Array.isArray(cfg.days)
          ? (cfg.days as unknown[])
              .map(d => Number(d))
              .filter(d => Number.isInteger(d) && d >= 0 && d <= 6)
          : [0, 1, 2, 3, 4];
        setWeeklyDays(days.length ? days : [0, 1, 2, 3, 4]);
      } else {
        setMode('daily');
        setTime(String(cfg.time || getCurrentTimeHHMM()));
      }
    }
  }, [editing, item, userTz]);

  // Reset every create-form field whenever the user (re-)enters create mode.
  // Without this, the component instance stays mounted across the
  // create → detail → create cycle (because the parent keeps rendering us
  // while either createScheduledMode or selectedScheduledAgentTaskId is set),
  // so the previous form's values leak into the next creation. Keying this
  // effect on `createMode` means it fires on first mount when createMode is
  // already true (a no-op since state is already default), and on every
  // false → true transition afterward (the actual bug surface).
  useEffect(() => {
    if (!createMode) return;
    // Smart-prompt state (prompt text, clarification thread, in-flight
    // flag, etc.) is owned by SmartPromptPanel and resets naturally
    // when that component unmounts on createMode = false → true cycles.
    setTitle('');
    setAgentTaskText('');
    setScheduleType('recurring');
    setTimezone(userTz);
    setMode('daily');
    setTime(getCurrentTimeHHMM());
    setIntervalMinutes(60);
    setRunAt(getDefaultRunAtLocal());
    setWeeklyDays([0, 1, 2, 3, 4]);
    setReferencePaths([]);
  }, [createMode, userTz]);

  useEffect(() => {
    if (!scheduledAgentTaskId || createMode) {
      setItem(null);
      setRuns([]);
      return;
    }
    setLoading(true);
    Promise.all([
      api.getScheduledAgentTask(scheduledAgentTaskId),
      api.listScheduledAgentTaskRuns(scheduledAgentTaskId, 100),
    ])
      .then(([agentTask, runList]) => {
        setItem(agentTask);
        setRuns(runList);
      })
      .finally(() => setLoading(false));
  }, [scheduledAgentTaskId, createMode]);

  const refreshRuns = useCallback(async () => {
    if (!item) return;
    const runList = await api.listScheduledAgentTaskRuns(item.id, 100);
    setRuns(runList);
  }, [item]);

  const scheduleConfig = useMemo(() => {
    if (scheduleType === 'one_time') {
      return { run_at: runAt };
    }
    if (mode === 'interval') {
      return { mode: 'interval', minutes: intervalMinutes };
    }
    if (mode === 'weekly') {
      const days = [...weeklyDays].filter(v => Number.isInteger(v) && v >= 0 && v <= 6).sort((a, b) => a - b);
      return { mode: 'weekly', days, time };
    }
    return { mode: 'daily', time };
  }, [scheduleType, mode, runAt, intervalMinutes, weeklyDays, time]);

  const create = async (sourceType: 'manual' | 'smart') => {
    setBusy(true);
    try {
      // Title is optional — if the user leaves it blank, derive one from
      // the AgentTask body so we always persist something human-readable
      // (used in sidebar rows and run notifications).
      const effectiveTitle = title.trim() || deriveTitleFromAgentTask(agentTaskText);
      const created = await api.createScheduledAgentTask({
        title: effectiveTitle,
        agent_task_text: agentTaskText,
        schedule_type: scheduleType,
        schedule_config: scheduleConfig,
        timezone,
        source_type: sourceType,
        is_active: true,
        reference_paths: referencePaths,
      });
      setItem(created);
      setRuns([]);
      onCreated?.(created.id);
      onExitCreateMode?.();
    } finally {
      setBusy(false);
    }
  };

  // Persist edits to an existing scheduled agent task. Reuses the same
  // `scheduleConfig` memo and effective-title fallback as the create flow,
  // so manual edits get the same defaulting / validation behavior. The
  // service layer recomputes next_run_at and re-enqueues the Huey task,
  // so we just have to swap the local item in state on success.
  const saveEdits = async () => {
    if (!item) return;
    setBusy(true);
    try {
      const effectiveTitle = title.trim() || deriveTitleFromAgentTask(agentTaskText);
      const updated = await api.updateScheduledAgentTask(item.id, {
        title: effectiveTitle,
        agent_task_text: agentTaskText,
        schedule_type: scheduleType,
        schedule_config: scheduleConfig,
        timezone,
        // Always send the post-edit list — including [] — so the user
        // can clear all attachments by removing every row before
        // saving. The TS payload type marks this optional; the backend
        // treats omission as "leave unchanged" and an empty array as
        // "clear all", which matches our intent here.
        reference_paths: referencePaths,
      });
      setItem(updated);
      setEditing(false);
      // Rescheduling recomputes next_run_at and replaces the pending
      // run on the backend. Refetch so the visible run history drops
      // the stale pending entry and shows the freshly enqueued one.
      await refreshRuns();
      onUpdated?.(updated.id);
    } finally {
      setBusy(false);
    }
  };

  // Apply a successful smart-prompt interpretation across the form's
  // controlled fields. SmartPromptPanel handles the API call and all
  // schedule-config parsing/normalization (cfg.run_at vs cfg.mode vs
  // cfg.minutes vs cfg.days); this callback only has to dispatch the
  // already-typed fields into the orchestrator's existing setters,
  // which the manual flow uses too.
  const applySmartFields = (fields: SmartScheduleFields) => {
    setTitle(fields.title);
    setAgentTaskText(fields.agentTaskText);
    setScheduleType(fields.scheduleType);
    setTimezone(fields.timezone);
    if (fields.mode !== undefined) setMode(fields.mode);
    if (fields.time !== undefined) setTime(fields.time);
    if (fields.intervalMinutes !== undefined) setIntervalMinutes(fields.intervalMinutes);
    if (fields.runAt !== undefined) setRunAt(fields.runAt);
    if (fields.weeklyDays !== undefined) setWeeklyDays(fields.weeklyDays);
  };

  const toggleWeekday = (day: number) => {
    setWeeklyDays(prev =>
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day].sort((a, b) => a - b)
    );
  };

  if (createMode) {
    return (
      <div className="main-content">
        <div className="result-container">
          <div className="result-header">
            <span className="result-label">Create Scheduled Task</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <SmartPromptPanel
              ref={smartPanelRef}
              userTimezone={timezone}
              busy={busy}
              setBusy={setBusy}
              onApply={applySmartFields}
            />

            <input
              className="sidebar-search-input"
              placeholder="Title (optional — derived from the task if left blank)"
              value={title}
              onChange={e => setTitle(e.target.value)}
            />
            <textarea
              className="sidebar-search-input"
              placeholder="Task text"
              value={agentTaskText}
              onChange={e => setAgentTaskText(e.target.value)}
              style={{ minHeight: 92, resize: 'vertical' }}
            />

            <AttachedFilesEditor paths={referencePaths} onChange={setReferencePaths} />

            <ScheduleControls
              scheduleType={scheduleType}
              onScheduleTypeChange={setScheduleType}
              mode={mode}
              onModeChange={setMode}
              time={time}
              onTimeChange={setTime}
              intervalMinutes={intervalMinutes}
              onIntervalMinutesChange={setIntervalMinutes}
              runAt={runAt}
              onRunAtChange={setRunAt}
              timezone={timezone}
              onTimezoneChange={setTimezone}
              timezoneOptions={timezoneOptions}
              weeklyDays={weeklyDays}
              onToggleWeekday={toggleWeekday}
            />

            <div className="overlay-actions">
              <button className="action-btn" onClick={onExitCreateMode}>Cancel</button>
              <button
                className="action-btn primary"
                onClick={() => create(smartPanelRef.current?.hasPromptText() ? 'smart' : 'manual')}
                disabled={busy || !agentTaskText.trim()}
              >
                Create Schedule
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!scheduledAgentTaskId) {
    return (
      <div className="empty-state" style={{ flex: 1 }}>
        <span>Select a scheduled task from the sidebar</span>
      </div>
    );
  }

  if (loading || !item) {
    return (
      <div className="empty-state" style={{ flex: 1 }}>
        <div className="loading-spinner" />
        <span>Loading scheduled task...</span>
      </div>
    );
  }

  // Meta row cell styling is reused for each of schedule / status / next-run
  // so the stacked block stays visually uniform.
  const metaRowStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontFamily: 'var(--font-family-light)',
    fontSize: 'var(--font-size-callout)',
    color: 'var(--text-secondary)',
    lineHeight: 1.4,
  };
  const metaLabelStyle: CSSProperties = {
    fontFamily: 'var(--font-family-medium)',
    color: 'var(--text-tertiary)',
    minWidth: 72,
  };

  return (
    <div className="main-content">
      <div className="result-container">
        <div
          className="result-header"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
        >
          <span className="result-label">{plainMarkdownText(item.title)}</span>
          {/* Active indicator pinned to the header's top-right. Uses
              --success-base (the app's success token) rather than the system
              default green so it stays in lockstep with the rest of the
              palette. Inactive schedules show a muted separator-colored dot
              to avoid the header looking broken when the state is off. */}
          <span
            aria-label={item.is_active ? 'Active' : 'Inactive'}
            title={item.is_active ? 'Active' : 'Inactive'}
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: item.is_active ? 'var(--success-base)' : 'var(--separator-color)',
              boxShadow: item.is_active
                ? '0 0 0 3px rgba(52, 199, 89, 0.18)'
                : 'none',
              flexShrink: 0,
            }}
          />
        </div>
        {editing ? (
          // ---------------------------------------------------------------
          // Inline edit panel. Reuses the same form-state slots as the
          // create flow (title / agentTaskText / scheduleType / mode / time /
          // intervalMinutes / runAt / weeklyDays / timezone) so the
          // memoized scheduleConfig derivation is shared. Save calls
          // updateScheduledAgentTask which both persists and re-enqueues the
          // Huey task in a single round trip.
          // ---------------------------------------------------------------
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 10 }}>
            <input
              className="sidebar-search-input"
              placeholder="Title (optional — derived from the task if left blank)"
              value={title}
              onChange={e => setTitle(e.target.value)}
            />
            <textarea
              className="sidebar-search-input"
              placeholder="Task text"
              value={agentTaskText}
              onChange={e => setAgentTaskText(e.target.value)}
              style={{ minHeight: 92, resize: 'vertical', fontFamily: 'var(--font-family-light)' }}
            />
            <AttachedFilesEditor paths={referencePaths} onChange={setReferencePaths} />

            <ScheduleControls
              scheduleType={scheduleType}
              onScheduleTypeChange={setScheduleType}
              mode={mode}
              onModeChange={setMode}
              time={time}
              onTimeChange={setTime}
              intervalMinutes={intervalMinutes}
              onIntervalMinutesChange={setIntervalMinutes}
              runAt={runAt}
              onRunAtChange={setRunAt}
              timezone={timezone}
              onTimezoneChange={setTimezone}
              timezoneOptions={timezoneOptions}
              weeklyDays={weeklyDays}
              onToggleWeekday={toggleWeekday}
            />

            <div className="overlay-actions">
              <button
                className="action-btn"
                onClick={() => setEditing(false)}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                className="action-btn primary"
                onClick={saveEdits}
                disabled={busy || !agentTaskText.trim()}
              >
                Save changes
              </button>
            </div>
          </div>
        ) : (
          <>
            <div style={{ marginBottom: 10 }}>
              <MarkdownRenderer content={item.agent_task_text} />
            </div>
            {/* Stacked meta block — one row each for schedule / status / next run
                so the values have room to breathe and "Status: active" isn't
                buried next to the rest. */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
              <div style={metaRowStyle}>
                <span style={metaLabelStyle}>Schedule</span>
                <span>{summarizeSchedule(item)}</span>
              </div>
              <div style={metaRowStyle}>
                <span style={metaLabelStyle}>Status</span>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '2px 8px',
                    borderRadius: 999,
                    fontFamily: 'var(--font-family-medium)',
                    fontSize: 'var(--font-size-status-small)',
                background: item.is_active
                  ? 'rgba(52, 199, 89, 0.14)'
                  : 'var(--background-tertiary)',
                color: item.is_active ? 'var(--success-base)' : 'var(--text-secondary)',
                border: `1px solid ${item.is_active ? 'var(--success-base)' : 'var(--separator-color)'}`,
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: item.is_active ? 'var(--success-base)' : 'var(--text-tertiary)',
                }}
              />
              {item.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
          {item.next_run_at && (
            <div style={metaRowStyle}>
              <span style={metaLabelStyle}>Next run</span>
              <span>{formatTimestamp12h(item.next_run_at)}</span>
            </div>
          )}
          <AttachedFilesDisplay paths={item.reference_paths ?? []} />
        </div>
            <div className="overlay-actions" style={{ marginBottom: 10 }}>
              <button
                className="action-btn"
                onClick={() => setEditing(true)}
              >
                Edit
              </button>
              <button
                className="action-btn"
                onClick={async () => {
                  const updated = await api.updateScheduledAgentTask(item.id, { is_active: !item.is_active });
                  setItem(updated);
                  // Deactivate cancels pending runs; activate re-enqueues.
                  // Keep the run list in sync without requiring a view reload.
                  await refreshRuns();
                }}
              >
                {item.is_active ? 'Deactivate' : 'Activate'}
              </button>
              <button
                className="action-btn"
                onClick={async () => {
                  await api.runScheduledAgentTaskNow(item.id);
                  await refreshRuns();
                }}
              >
                Run Now
              </button>
            </div>
          </>
        )}
        <ScheduledRunHistoryList runs={runs} onViewAgentTask={onViewAgentTask} />
      </div>
    </div>
  );
}
