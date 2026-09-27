import type {
  ActionDecision,
  ActionEditFields,
  ProgressState,
  ProposedAction,
  ReconciliationConfig,
  ReconciliationSession,
  WSEvent,
} from '../types';
import {
  commitSession as apiCommit,
  decideAction as apiDecide,
  discardSession as apiDiscard,
  getSession as apiGetSession,
} from '../services/api';

const EVENT_PREFIX = 'skill_reconciliation_';

export interface StoreState {
  config: ReconciliationConfig | null;
  session: ReconciliationSession | null;
  selectedActionId: string | null;
  error: string | null;
  committing: boolean;
}

/**
 * Minimal observable store. Progress events are patched locally (cheap, high
 * frequency); action/status events trigger a debounced refetch of GET /session
 * so the action list stays authoritative with the backend (notify-then-refetch).
 */
class ReconciliationStore {
  private state: StoreState = {
    config: null,
    session: null,
    selectedActionId: null,
    error: null,
    committing: false,
  };

  private listeners = new Set<() => void>();
  private refetchTimer: ReturnType<typeof setTimeout> | null = null;

  getState = (): StoreState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private set(patch: Partial<StoreState>) {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  init(config: ReconciliationConfig) {
    this.set({ config });
  }

  selectAction(actionId: string | null) {
    this.set({ selectedActionId: actionId });
  }

  handleEvent(event: WSEvent) {
    if (!event.event_type.startsWith(EVENT_PREFIX)) return;
    if (event.event_type === 'skill_reconciliation_progress') {
      const progress = event.progress as ProgressState | undefined;
      if (progress && this.state.session) {
        this.set({
          session: { ...this.state.session, progress },
        });
      }
      return;
    }
    // action_ready + status: refetch the authoritative session.
    this.scheduleRefetch();
  }

  private scheduleRefetch() {
    if (this.refetchTimer) return;
    this.refetchTimer = setTimeout(() => {
      this.refetchTimer = null;
      void this.refetchSession();
    }, 150);
  }

  async refetchSession(): Promise<void> {
    const { config } = this.state;
    if (!config) return;
    try {
      const session = await apiGetSession(config.apiBaseUrl);
      this.applySession(session);
    } catch {
      // 404 before a session exists is expected; ignore.
    }
  }

  private applySession(session: ReconciliationSession) {
    let selected = this.state.selectedActionId;
    const stillExists = session.actions.some((action) => action.id === selected);
    if (!stillExists) {
      selected = session.actions.length > 0 ? session.actions[0].id : null;
    }
    this.set({ session, selectedActionId: selected });
  }

  setSession(session: ReconciliationSession) {
    this.applySession(session);
  }

  async decide(actionId: string, decision: ActionDecision, edited?: ActionEditFields): Promise<void> {
    const { config } = this.state;
    if (!config) return;
    try {
      const updated: ProposedAction = await apiDecide(config.apiBaseUrl, actionId, decision, edited);
      const session = this.state.session;
      if (session) {
        this.set({
          session: {
            ...session,
            actions: session.actions.map((action) =>
              action.id === updated.id ? updated : action,
            ),
          },
          error: null,
        });
      }
    } catch (err) {
      this.set({ error: `Failed to record decision: ${String(err)}` });
    }
  }

  async commit(): Promise<void> {
    const { config } = this.state;
    if (!config) return;
    this.set({ committing: true, error: null });
    try {
      const session = await apiCommit(config.apiBaseUrl);
      this.applySession(session);
    } catch (err) {
      this.set({ error: `Commit failed: ${String(err)}` });
    } finally {
      this.set({ committing: false });
    }
  }

  async discardAndClose(): Promise<void> {
    const { config } = this.state;
    if (config) {
      try {
        await apiDiscard(config.apiBaseUrl);
      } catch {
        // The native host also fires discard on window close; ignore errors.
      }
    }
  }
}

export const store = new ReconciliationStore();
