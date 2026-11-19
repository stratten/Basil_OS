import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ExclusionWindow, ScheduledAgentTask, ScheduledAgentTaskRun } from '../../types';
import * as api from '../../services/api';
import { startScheduledRunNow } from '../../services/scheduledRunNow';
import AttachedFilesDisplay from './AttachedFilesDisplay';
import AttachedFilesEditor from './AttachedFilesEditor';
import ScheduleControls from './ScheduleControls';
import ScheduledRunHistoryList from './ScheduledRunHistoryList';
import ScheduledConnectionsField, { connectionsChanged } from './ScheduledConnectionsField';
import ScheduledModelField from './ScheduledModelField';
import ScheduledMeta from './ScheduledMeta';
import ScheduledTextFields from './ScheduledTextFields';
import ScheduledChainField from './ScheduledChainField';
import ScheduledExclusionWindowsField from './ScheduledExclusionWindowsField';
import ScheduledFormSection from './ScheduledFormSection';
import {
  DEFAULT_CHAIN_FORM,
  chainConfigChanged,
  chainFormError,
  chainFormFromConfig,
  effectiveChainConfig,
  exclusionWindowsError,
  exclusionWindowsFromConfig,
  withExclusionWindows,
  type ChainFormState,
} from './scheduledChainHelpers';
import { plainMarkdownText } from '../../../../shared/text/plainMarkdownText';
import MarkdownRenderer from '../MarkdownRenderer';
import SmartPromptPanel, {
  type SmartPromptPanelHandle,
  type SmartScheduleFields,
} from './SmartPromptPanel';
import {
  buildTimezoneOptions,
  deriveTitleFromAgentTask,
  getCurrentTimeHHMM,
  composeFirstRun,
  firstRunFromNextRun,
  getDefaultRunAtLocal,
  getUserTimezone,
  scheduleFormBlocker,
  splitFirstRun,
} from './scheduledAgentTaskHelpers';

interface Props {
  scheduledAgentTaskId?: string | null;
  createMode: boolean;
  onCreated?: (scheduledAgentTaskId: string) => void;
  onExitCreateMode?: () => void;
  // Fired after a successful inline edit so the parent can refresh any
  // dependent surfaces (e.g. bump the sidebar's scheduledListVersion so a
  // renamed schedule's row label updates without a manual view toggle).
  onUpdated?: (scheduledAgentTaskId: string) => void;
  // Bumped by the parent when a schedule changes somewhere else, such as a pause or resume from its sidebar row. When it changes, the open schedule and its runs are fetched again so this view never shows a stale Active or Inactive state.
  scheduledListVersion?: number;
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
  scheduledListVersion,
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
  // Optional first run for the interval mode, edited as a time of day plus an
  // optional date. Both empty means "count from when saved"; a time alone means
  // its next occurrence in the schedule's timezone.
  const [startDate, setStartDate] = useState('');
  const [startTime, setStartTime] = useState('');
  const [runAt, setRunAt] = useState<string>(() => getDefaultRunAtLocal());
  // Mon=0 .. Sun=6 — default to weekdays selected.
  const [weeklyDays, setWeeklyDays] = useState<number[]>([0, 1, 2, 3, 4]);
  // Daily time ranges in which a recurring schedule does not run; empty means none.
  const [exclusionWindows, setExclusionWindows] = useState<ExclusionWindow[]>([]);
  // Whether each run is its own task or continues one conversation, and the limits that start a new one. Sent whole on create when chained, and on edit only when it changed.
  const [chainForm, setChainForm] = useState<ChainFormState>({ ...DEFAULT_CHAIN_FORM });
  const [busy, setBusy] = useState(false);
  // Result of the last Run Now press: shown under the buttons, because the backend reports a run that could not start in the response rather than as an error.
  const [runNow, setRunNow] = useState<{ starting: boolean; failure: string | null }>({ starting: false, failure: null });

  // Absolute filesystem paths the user has attached as context for this
  // scheduled agent task. Hydrated from the loaded ``item`` in the read view
  // and from the same item when entering edit mode; cleared on each
  // (re-)entry into create mode. The full list is sent on every save —
  // PATCH receives the post-edit array verbatim and replaces what the
  // backend has stored. ``AttachedFilesEditor`` owns the picker-bridge
  // wiring and append/dedupe logic; this orchestrator just holds the
  // canonical list and passes it through as a controlled value.
  const [referencePaths, setReferencePaths] = useState<string[]>([]);

  // Reasoning model pinned to this schedule; '' means "use the default
  // model". Sent as-is on create and when it changed on edit (an empty
  // string is the PATCH value that clears a previous pin).
  const [modelId, setModelId] = useState('');
  // Models the user can pick from. A failed load just leaves the list
  // empty: the schedule keeps working with the default model.
  const [models, setModels] = useState<api.ReasoningModel[]>([]);
  useEffect(() => {
    let canceled = false;
    api.getReasoningModels()
      .then(response => { if (!canceled) setModels(response.models); })
      .catch(() => { /* leave the picker empty; default model still applies */ });
    return () => { canceled = true; };
  }, []);

  // Connections (MCP) this schedule is tied to. Sent whole on create, and on edit only when the selection changed, so an unrelated edit is never rejected because an earlier tag has since been removed.
  const [connectionIds, setConnectionIds] = useState<string[]>([]);
  // The connections the user can choose from. A failed load leaves the picker hidden and `connectionsLoaded` false, so the schedule keeps its tags untouched.
  const [connections, setConnections] = useState<api.ScheduleConnection[]>([]);
  const [connectionsLoaded, setConnectionsLoaded] = useState(false);
  useEffect(() => {
    let canceled = false;
    api.listScheduleConnections()
      .then(response => {
        if (canceled) return;
        setConnections(response.connections);
        setConnectionsLoaded(true);
      })
      .catch(() => { /* leave the picker hidden; the schedule's tags stay as saved */ });
    return () => { canceled = true; };
  }, []);

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
    setConnectionIds(Array.isArray(item.connection_ids) ? [...item.connection_ids] : []);
    setModelId(item.model_id || '');
    setChainForm(chainFormFromConfig(item.chain_config));
    setExclusionWindows(exclusionWindowsFromConfig(item.schedule_config));
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
        // The next run is what the reader sees and edits here, so an unrelated edit keeps it instead of restarting the interval from now.
        const upcoming = firstRunFromNextRun(item.is_active ? item.next_run_at : null, item.timezone || userTz);
        setStartDate(upcoming.date);
        setStartTime(upcoming.time);
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
    setStartDate('');
    setStartTime('');
    setRunAt(getDefaultRunAtLocal());
    setWeeklyDays([0, 1, 2, 3, 4]);
    setReferencePaths([]);
    setConnectionIds([]);
    setModelId('');
    setChainForm({ ...DEFAULT_CHAIN_FORM });
    setExclusionWindows([]);
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

  // Refetch quietly when the schedule changed elsewhere. It is skipped while the edit form is open, because a fresh item would overwrite what the user is typing, and it is not tied to the first render, which the effect above already loads.
  const seenListVersion = useRef(scheduledListVersion);
  useEffect(() => {
    if (scheduledListVersion === seenListVersion.current) return undefined;
    seenListVersion.current = scheduledListVersion;
    if (!scheduledAgentTaskId || createMode || editing) return undefined;
    let canceled = false;
    Promise.all([
      api.getScheduledAgentTask(scheduledAgentTaskId),
      api.listScheduledAgentTaskRuns(scheduledAgentTaskId, 100),
    ])
      .then(([agentTask, runList]) => {
        if (canceled) return;
        setItem(agentTask);
        setRuns(runList);
      })
      .catch((err) => console.error('[ScheduledAgentTaskDetail] Failed to refresh the schedule', err));
    return () => {
      canceled = true;
    };
  }, [scheduledListVersion, scheduledAgentTaskId, createMode, editing]);

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
      // start_at is omitted when blank so the stored config stays identical to
      // what interval schedules saved before this field existed.
      const startAt = composeFirstRun({ date: startDate, time: startTime }, timezone);
      return withExclusionWindows(
        startAt
          ? { mode: 'interval', minutes: intervalMinutes, start_at: startAt }
          : { mode: 'interval', minutes: intervalMinutes },
        exclusionWindows,
      );
    }
    if (mode === 'weekly') {
      const days = [...weeklyDays].filter(v => Number.isInteger(v) && v >= 0 && v <= 6).sort((a, b) => a - b);
      return withExclusionWindows({ mode: 'weekly', days, time }, exclusionWindows);
    }
    return withExclusionWindows({ mode: 'daily', time }, exclusionWindows);
  }, [scheduleType, mode, runAt, intervalMinutes, startDate, startTime, timezone, weeklyDays, time, exclusionWindows]);

  // A date with no time would be dropped silently, so saving waits until the reader adds the time or clears the date.
  const firstRunIncomplete = scheduleType === 'recurring' && mode === 'interval' && startDate !== '' && startTime === '';

  // Chain limits or quiet-hours windows the backend would reject. The reason is shown beside the field, and Create and Save stay disabled until it is fixed.
  const scheduleFormError = scheduleType === 'recurring' ? (chainFormError(chainForm) ?? exclusionWindowsError(exclusionWindows)) : null;
  // Why Create and Save are unavailable, shown under them so a dimmed button is never a puzzle.
  const formBlocker = scheduleFormBlocker({ taskText: agentTaskText, firstRunIncomplete, formError: scheduleFormError });

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
        // Omitted when nothing is tagged so the payload stays the same as
        // before this field existed.
        ...(connectionIds.length ? { connection_ids: connectionIds } : {}),
        // Omitted when the user kept the default so the payload stays the
        // same as before this field existed.
        ...(modelId ? { model_id: modelId } : {}),
        // Omitted for independent runs so the payload stays the same as before this field existed.
        ...(scheduleType === 'recurring' && (chainForm.chained || chainForm.carryChecklist) ? { chain_config: effectiveChainConfig(chainForm, scheduleType) } : {}),
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
        // Only send the tags when they changed. An unchanged list that names a
        // connection removed since would otherwise fail validation on an
        // unrelated edit. [] removes every tag.
        ...(connectionsChanged(connectionIds, item.connection_ids) ? { connection_ids: connectionIds } : {}),
        // Only send the model when it changed. Re-sending an unchanged pin
        // that has since become unavailable would make an unrelated edit
        // fail validation. '' clears the pin back to the default model.
        ...(modelId !== (item.model_id || '') ? { model_id: modelId } : {}),
        // Only send the chain settings when they changed, and never a chain for a one-time schedule. {mode: 'independent'} stops chaining.
        ...(chainConfigChanged(chainForm, item.chain_config, scheduleType)
          ? { chain_config: effectiveChainConfig(chainForm, scheduleType) }
          : {}),
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
    // Always assigned for the interval mode so a previous manual first run
    // can't leak into a smart-generated schedule that didn't ask for one.
    if (fields.mode === 'interval') {
      const requested = splitFirstRun(fields.startAt ?? '');
      setStartDate(requested.date);
      setStartTime(requested.time);
    }
    if (fields.runAt !== undefined) setRunAt(fields.runAt);
    if (fields.weeklyDays !== undefined) setWeeklyDays(fields.weeklyDays);
    if (fields.exclusionWindows !== undefined) setExclusionWindows(fields.exclusionWindows);
  };

  const toggleWeekday = (day: number) => {
    setWeeklyDays(prev =>
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day].sort((a, b) => a - b)
    );
  };

  // The form rows shared by the create form and the inline edit form, so the two can never drift apart.
  const formFields = (startLabel: string) => (
    <>
      <ScheduledFormSection title="Task">
        <ScheduledTextFields title={title} onTitleChange={setTitle} taskText={agentTaskText} onTaskTextChange={setAgentTaskText} />
        <AttachedFilesEditor paths={referencePaths} onChange={setReferencePaths} />
      </ScheduledFormSection>

      <ScheduledFormSection title="Tools">
        <ScheduledConnectionsField connections={connections} selectedIds={connectionIds} onChange={setConnectionIds} loaded={connectionsLoaded} disabled={busy} />
        <ScheduledModelField models={models} modelId={modelId} onChange={setModelId} disabled={busy} />
      </ScheduledFormSection>

      <ScheduledFormSection title="Schedule">
        <ScheduleControls
          scheduleType={scheduleType}
          onScheduleTypeChange={setScheduleType}
          mode={mode}
          onModeChange={setMode}
          time={time}
          onTimeChange={setTime}
          intervalMinutes={intervalMinutes}
          onIntervalMinutesChange={setIntervalMinutes}
          startDate={startDate}
          onStartDateChange={setStartDate}
          startTime={startTime}
          onStartTimeChange={setStartTime}
          startLabel={startLabel}
          runAt={runAt}
          onRunAtChange={setRunAt}
          timezone={timezone}
          onTimezoneChange={setTimezone}
          timezoneOptions={timezoneOptions}
          weeklyDays={weeklyDays}
          onToggleWeekday={toggleWeekday}
        />
        {scheduleType === 'recurring' && (
          <ScheduledExclusionWindowsField windows={exclusionWindows} onChange={setExclusionWindows} disabled={busy} />
        )}
        {scheduleType === 'recurring' && (
          <ScheduledChainField form={chainForm} onChange={setChainForm} disabled={busy} />
        )}
      </ScheduledFormSection>
    </>
  );

  // The line under Create and Save that names what is missing. Absent when nothing blocks the button.
  const blockerLine = formBlocker ? <p id="schedule-form-blocker" className="scheduled-form__blocker">{formBlocker}</p> : null;

  if (createMode) {
    return (
      <div className="main-content">
        <div className="result-container">
          <div className="result-header">
            <span className="result-label">Create Scheduled Task</span>
          </div>
          <div className="scheduled-form">
            <SmartPromptPanel
              ref={smartPanelRef}
              userTimezone={timezone}
              busy={busy}
              setBusy={setBusy}
              onApply={applySmartFields}
            />

            {formFields('First run')}

            <div className="overlay-actions">
              <button className="action-btn action-btn--neutral" onClick={onExitCreateMode}>Cancel</button>
              <button
                className="action-btn primary"
                onClick={() => create(smartPanelRef.current?.hasPromptText() ? 'smart' : 'manual')}
                disabled={busy || Boolean(formBlocker)}
                aria-describedby={formBlocker ? 'schedule-form-blocker' : undefined}
              >
                Create Schedule
              </button>
            </div>
            {blockerLine}
          </div>
        </div>
      </div>
    );
  }

  if (!scheduledAgentTaskId) {
    return (
      <div className="empty-state scheduled-detail__fill">
        <span>Select a scheduled task from the sidebar</span>
      </div>
    );
  }

  if (loading || !item) {
    return (
      <div className="empty-state scheduled-detail__fill">
        <div className="loading-spinner" />
        <span>Loading scheduled task...</span>
      </div>
    );
  }

  return (
    <div className="main-content">
      <div className="result-container">
        <div className="result-header scheduled-detail__header">
          <span className="result-label">{plainMarkdownText(item.title)}</span>
          {/* The schedule's state, pinned to the header's top-right: a solid green dot (--success-base) when it is active and a hollow ring in the text color when it is inactive, matching the sidebar row, with the word beside it. */}
          <span className="scheduled-detail__state">
            <span
              className={`agent-task-row__schedule-dot scheduled-detail__active-dot ${item.is_active ? 'is-active' : 'is-inactive'}`}
              aria-label={item.is_active ? 'Active' : 'Inactive'}
              title={item.is_active ? 'Active' : 'Inactive'}
            />
            <span aria-hidden="true">{item.is_active ? 'Active' : 'Inactive'}</span>
          </span>
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
          <div className="scheduled-form">
            {formFields('Next run')}

            <div className="overlay-actions">
              <button
                className="action-btn action-btn--neutral"
                onClick={() => setEditing(false)}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                className="action-btn primary"
                onClick={saveEdits}
                disabled={busy || Boolean(formBlocker)}
                aria-describedby={formBlocker ? 'schedule-form-blocker' : undefined}
              >
                Save changes
              </button>
            </div>
            {blockerLine}
          </div>
        ) : (
          <>
            <div className="scheduled-detail__task">
              <MarkdownRenderer content={item.agent_task_text} />
            </div>
            <ScheduledMeta item={item} models={models} connections={connections} connectionsLoaded={connectionsLoaded} />
            <AttachedFilesDisplay paths={item.reference_paths ?? []} />
            <div className="scheduled-actions">
              <button
                className="action-btn primary"
                disabled={runNow.starting}
                onClick={async () => {
                  setRunNow({ starting: true, failure: null });
                  const outcome = await startScheduledRunNow(item.id);
                  setRunNow({ starting: false, failure: outcome.ok ? null : (outcome.message ?? null) });
                  await refreshRuns();
                }}
              >
                Run Now
              </button>
              <button
                className="action-btn action-btn--neutral"
                onClick={() => setEditing(true)}
              >
                Edit
              </button>
              <button
                className="action-btn action-btn--neutral"
                onClick={async () => {
                  const updated = await api.updateScheduledAgentTask(item.id, { is_active: !item.is_active });
                  setItem(updated);
                  // The sidebar row's dot shows is_active, so tell the parent to reload the list now instead of when the view is next switched.
                  onUpdated?.(updated.id);
                  // Deactivate cancels pending runs; activate re-enqueues.
                  // Keep the run list in sync without requiring a view reload.
                  await refreshRuns();
                }}
              >
                {item.is_active ? 'Deactivate' : 'Activate'}
              </button>
            </div>
            {runNow.failure && (
              <p role="alert" className="scheduled-notice">
                {runNow.failure}
              </p>
            )}
          </>
        )}
        <ScheduledRunHistoryList runs={runs} onViewAgentTask={onViewAgentTask} />
      </div>
    </div>
  );
}
