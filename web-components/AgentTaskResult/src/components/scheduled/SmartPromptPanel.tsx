import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import * as api from '../../services/api';
import { getCurrentTimeHHMM, getDefaultRunAtLocal } from './scheduledAgentTaskHelpers';

// Fields the panel hands the parent after a successful smart-prompt
// interpretation. Mirrors the orchestrator's controlled-field shape so
// the parent can dispatch each into its existing state setters without
// any additional parsing — the panel does all the cfg.run_at /
// cfg.mode / cfg.minutes / cfg.days normalization here so the smart
// flow's field-massaging logic stays bundled with the rest of the
// smart UI.
export interface SmartScheduleFields {
  title: string;
  agentTaskText: string;
  scheduleType: 'one_time' | 'recurring';
  timezone: string;
  mode?: 'daily' | 'weekly' | 'interval';
  time?: string;
  intervalMinutes?: number;
  runAt?: string;
  weeklyDays?: number[];
}

// Imperative handle the parent can use to query smart-prompt state from
// callbacks that don't have access to the panel's internal state — in
// particular, the form's bottom "Create Schedule" button needs to know
// whether to label the create call as `'smart'` or `'manual'` for
// downstream analytics.
export interface SmartPromptPanelHandle {
  hasPromptText(): boolean;
}

interface Props {
  userTimezone: string;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onApply: (fields: SmartScheduleFields) => void;
}

// Small in-button spinner that piggybacks on the global `@keyframes spin`
// already defined in components.css. Uses currentColor so the ring matches
// the surrounding button text in both default and primary button variants
// without needing a per-variant CSS rule.
function InlineSpinner({ size = 12 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: '2px solid currentColor',
        borderTopColor: 'transparent',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
        opacity: 0.85,
        flexShrink: 0,
      }}
    />
  );
}

// Sticky header for the create form: a plain-language textarea ("check
// my inbox every weekday at 8am"), a Generate button that POSTs to the
// scheduled-agent-task interpretation endpoint, an inline clarification
// follow-up surface for when the LLM needs more info, and an error
// banner. On a successful interpretation, hands the parsed schedule
// fields up via `onApply` so the parent can populate its existing
// controlled inputs (title / agentTaskText / scheduleType / mode / etc.)
// — the parent stays the source of truth for those fields and the
// SmartPromptPanel just acts as a sophisticated form-filler.
const SmartPromptPanel = forwardRef<SmartPromptPanelHandle, Props>(
  function SmartPromptPanel({ userTimezone, busy, setBusy, onApply }, ref) {
    const [smartPrompt, setSmartPrompt] = useState('');
    const [smartContextId, setSmartContextId] = useState<string | null>(null);
    const [smartClarification, setSmartClarification] = useState<string>('');
    const [smartError, setSmartError] = useState<string>('');
    const [interpreting, setInterpreting] = useState(false);
    const [clarificationResponse, setClarificationResponse] = useState<string>('');
    const clarificationInputRef = useRef<HTMLTextAreaElement | null>(null);

    useImperativeHandle(ref, () => ({
      hasPromptText: () => smartPrompt.trim().length > 0,
    }), [smartPrompt]);

    const generateFromPrompt = async (overridePrompt?: string) => {
      const text = (overridePrompt ?? smartPrompt).trim();
      if (!text) return;
      setBusy(true);
      setInterpreting(true);
      try {
        setSmartError('');
        const interpreted = await api.interpretScheduledAgentTaskPrompt(text, {
          contextId: smartContextId || undefined,
          userTimezone,
        });
        if (!interpreted.success) {
          if (interpreted.needs_user_confirmation) {
            setSmartClarification(interpreted.clarification_question || 'Please clarify your schedule details.');
            setSmartContextId(interpreted.context_id || smartContextId);
            // Clear the in-flight clarification answer so the input is empty
            // for the next follow-up question (which can be a chained
            // clarification).
            setClarificationResponse('');
            // Defer focus until the input has rendered.
            setTimeout(() => clarificationInputRef.current?.focus(), 0);
            return;
          }
          setSmartError(interpreted.error || 'Unable to interpret scheduling request.');
          return;
        }

        setSmartClarification('');
        setSmartContextId(null);
        setClarificationResponse('');
        if (
          !interpreted.title ||
          !interpreted.agent_task_text ||
          !interpreted.schedule_type ||
          !interpreted.schedule_config ||
          !interpreted.timezone
        ) {
          setSmartError('Schedule interpretation response was missing required fields.');
          return;
        }

        const cfg = interpreted.schedule_config || {};
        const fields: SmartScheduleFields = {
          title: interpreted.title,
          agentTaskText: interpreted.agent_task_text,
          scheduleType: interpreted.schedule_type === 'one_time' ? 'one_time' : 'recurring',
          timezone: interpreted.timezone || userTimezone,
        };
        if (interpreted.schedule_type === 'one_time') {
          fields.runAt = String(cfg.run_at || getDefaultRunAtLocal());
        } else {
          const derivedMode = String(cfg.mode || 'daily');
          if (derivedMode === 'interval') {
            fields.mode = 'interval';
            fields.intervalMinutes = Number(cfg.minutes || 60);
          } else if (derivedMode === 'weekly') {
            fields.mode = 'weekly';
            fields.time = String(cfg.time || getCurrentTimeHHMM());
            if (Array.isArray(cfg.days)) {
              const days = (cfg.days as unknown[])
                .map(d => Number(d))
                .filter(v => Number.isInteger(v) && v >= 0 && v <= 6);
              fields.weeklyDays = days.length > 0 ? days : [0, 1, 2, 3, 4];
            }
          } else {
            fields.mode = 'daily';
            fields.time = String(cfg.time || getCurrentTimeHHMM());
          }
        }
        onApply(fields);
      } finally {
        setBusy(false);
        setInterpreting(false);
      }
    };

    return (
      <>
        <textarea
          className="sidebar-search-input"
          placeholder="Describe a schedule in plain language: e.g. check my inbox every weekday at 8am..."
          value={smartPrompt}
          onChange={e => setSmartPrompt(e.target.value)}
          disabled={!!smartClarification || interpreting}
          aria-busy={interpreting}
          style={{ minHeight: 64, resize: 'vertical', fontFamily: 'var(--font-family-light)' }}
        />
        <div
          className="overlay-actions"
          style={{ justifyContent: 'flex-start', alignItems: 'center', gap: 10 }}
        >
          <button
            className="action-btn"
            onClick={() => generateFromPrompt()}
            disabled={busy || !smartPrompt.trim() || !!smartClarification}
            aria-busy={interpreting && !smartClarification}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            {interpreting && !smartClarification && <InlineSpinner />}
            {interpreting && !smartClarification ? 'Interpreting…' : 'Generate schedule'}
          </button>
          {interpreting && !smartClarification && (
            <span
              role="status"
              aria-live="polite"
              style={{
                fontFamily: 'var(--font-family-light)',
                fontSize: 'var(--font-size-callout)',
                color: 'var(--text-tertiary)',
              }}
            >
              Interpreting your request…
            </span>
          )}
        </div>
        {smartClarification && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              padding: 10,
              border: '1px solid var(--warning-base)',
              borderRadius: 6,
              background: 'rgba(255, 165, 0, 0.05)',
              fontFamily: 'var(--font-family-light)',
              fontSize: 'var(--font-size-callout)',
              color: 'var(--text-primary)',
            }}
          >
            <div style={{ color: 'var(--warning-base)' }}>
              <strong style={{ fontFamily: 'var(--font-family-medium)' }}>Needs clarification:</strong>{' '}
              {smartClarification}
            </div>
            <textarea
              ref={clarificationInputRef}
              className="sidebar-search-input"
              placeholder="Type your response…"
              value={clarificationResponse}
              onChange={e => setClarificationResponse(e.target.value)}
              onKeyDown={e => {
                // Cmd/Ctrl+Enter submits; bare Enter inserts a newline.
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && clarificationResponse.trim() && !busy) {
                  e.preventDefault();
                  generateFromPrompt(clarificationResponse);
                }
              }}
              disabled={busy}
              style={{ minHeight: 56, resize: 'vertical', fontFamily: 'var(--font-family-light)' }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                className="action-btn"
                onClick={() => {
                  setSmartClarification('');
                  setSmartContextId(null);
                  setClarificationResponse('');
                }}
                disabled={busy}
              >
                Discard
              </button>
              <button
                className="action-btn primary"
                onClick={() => generateFromPrompt(clarificationResponse)}
                disabled={busy || !clarificationResponse.trim()}
                aria-busy={interpreting}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
              >
                {interpreting && <InlineSpinner />}
                {interpreting ? 'Interpreting…' : 'Send response'}
              </button>
            </div>
          </div>
        )}
        {smartError && (
          <div
            className="error-section"
            style={{ fontFamily: 'var(--font-family-light)' }}
          >
            {smartError}
          </div>
        )}
      </>
    );
  }
);

export default SmartPromptPanel;
