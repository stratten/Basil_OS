import { useMemo, useState } from 'react';
import { useReconciliationBridge } from './app/useReconciliationBridge';
import { store } from './app/reconciliationStore';
import { closeWorkspace, collapseWorkspace, expandWorkspace, minimizeWorkspace } from './services/bridge';
import { Header } from './components/Header';
import { ProgressBanner } from './components/ProgressBanner';
import { ActionList } from './components/ActionList';
import { ActionDetail } from './components/ActionDetail';
import { CommitBar } from './components/CommitBar';
import { EmptyState } from './components/EmptyState';
import { SingleSightingsList } from './components/SingleSightingsList';

type WorkspaceTab = 'proposals' | 'single_sightings';

export default function App() {
  const state = useReconciliationBridge();
  const session = state.session;
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('proposals');
  const [isCollapsed, setIsCollapsed] = useState(false);

  const toggleCollapsed = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    if (next) {
      collapseWorkspace();
    } else {
      expandWorkspace();
    }
  };

  const selectedAction = useMemo(
    () => session?.actions.find((action) => action.id === state.selectedActionId) ?? null,
    [session, state.selectedActionId],
  );

  const minObservations = session?.snapshot.min_observations ?? 2;
  const singleSightings = useMemo(
    () =>
      (session?.snapshot.pending_candidates ?? []).filter(
        (candidate) => candidate.observation_count < minObservations,
      ),
    [session, minObservations],
  );

  const acceptedCount = session?.actions.filter((a) => a.decision === 'accepted').length ?? 0;
  const pendingCount = session?.actions.filter((a) => a.decision === 'pending').length ?? 0;
  const committed = session?.status === 'committed';
  const locked = committed || state.committing;

  const handleClose = () => {
    void store.discardAndClose();
    closeWorkspace();
  };

  const summary = session
    ? `${session.snapshot.pending_candidates.length} pending · ${session.snapshot.saved_skills.length} saved skills`
    : 'Starting…';

  return (
    <div className="basil-webkit-window-frame">
      <div className="widget-root basil-webkit-window-surface">
      <Header
        summary={summary}
        isCollapsed={isCollapsed}
        onMinimize={minimizeWorkspace}
        onClose={handleClose}
        onToggleCollapse={toggleCollapsed}
      />

      <div
        className={`workspace-collapsible${isCollapsed ? ' is-collapsed' : ''}`}
        aria-hidden={isCollapsed}
        {...(isCollapsed ? { inert: '' } : {})}
      >
        {session && <ProgressBanner progress={session.progress} status={session.status} />}

        {state.error && <div className="result-action-message error" style={{ margin: '8px 16px' }}>{state.error}</div>}

        {session && (
          <div className="workspace-tabs">
            <button
              className={`workspace-tab${activeTab === 'proposals' ? ' active' : ''}`}
              onClick={() => setActiveTab('proposals')}
            >
              Proposals ({session.actions.length})
            </button>
            <button
              className={`workspace-tab${activeTab === 'single_sightings' ? ' active' : ''}`}
              onClick={() => setActiveTab('single_sightings')}
            >
              Single sightings ({singleSightings.length})
            </button>
          </div>
        )}

        <div className="workspace-body">
          {activeTab === 'single_sightings' && session ? (
            <SingleSightingsList candidates={singleSightings} minObservations={minObservations} />
          ) : !session || session.actions.length === 0 ? (
            <EmptyState
              title={
                !session
                  ? 'Preparing workspace…'
                  : session.status === 'analyzing'
                    ? 'Analyzing…'
                    : 'Nothing to reconcile'
              }
              message={
                !session
                  ? 'Connecting to the reconciliation session.'
                  : session.status === 'analyzing'
                    ? 'Proposals will appear here as they are computed.'
                    : 'No duplicate or enhancement proposals were found for the recurring pending candidates.'
              }
            />
          ) : (
            <>
              <ActionList
                actions={session.actions}
                snapshot={session.snapshot}
                selectedId={state.selectedActionId}
                onSelect={(id) => store.selectAction(id)}
              />
              {selectedAction ? (
                <ActionDetail
                  action={selectedAction}
                  snapshot={session.snapshot}
                  locked={locked}
                  onDecide={(decision, edited) => void store.decide(selectedAction.id, decision, edited)}
                />
              ) : (
                <EmptyState title="Select a proposal" message="Choose a proposal on the left to review it." />
              )}
            </>
          )}
        </div>

        {session && (
          <CommitBar
            acceptedCount={acceptedCount}
            pendingCount={pendingCount}
            committing={state.committing}
            status={session.status}
            onCommit={() => void store.commit()}
            onClose={handleClose}
          />
        )}
      </div>
    </div>
    </div>
  );
}
