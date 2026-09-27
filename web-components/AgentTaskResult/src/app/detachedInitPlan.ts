// Decides how a window should hydrate on init, isolated as a pure function so
// the detached-window chain-loading rules are unit-testable without rendering
// the host bridge hook.
//
// The bug this guards against: a detached window is expected to load the whole
// task thread via hydrateDetachedChain (which reads detail.follow_ups). The
// main window merges all follow-up state onto the root entry, so the host
// commonly hands off the same id as both the initial task and the chain root.
// The previous guard skipped chain hydration whenever those ids matched,
// leaving a fully terminal multi-turn chain showing only the root and a live
// pop showing a root+latest composite with the middle turns missing.

export interface DetachedInitConfig {
  initialAgentTaskId?: string | null;
  detachedRootTaskId?: string | null;
}

export interface DetachedInitPlan {
  // When set, call hydrateAgentFromBackend(id) for the initial task. Only used
  // for non-detached windows; detached windows let hydrateDetachedChain own
  // reconciliation (self-hydration there would drop follow_ups and can clobber
  // the most-recent result with the root's own turn).
  selfHydrateInitialTaskId: string | null;
  // When set, call hydrateDetachedChain(id) to load the full chain onto the
  // root entry. Always set for a detached window, regardless of whether it
  // equals the initial task id.
  hydrateChainRootId: string | null;
}

export function planDetachedInitHydration(config: DetachedInitConfig): DetachedInitPlan {
  const initialAgentTaskId = config.initialAgentTaskId || null;
  const detachedRootTaskId = config.detachedRootTaskId || null;

  return {
    selfHydrateInitialTaskId:
      initialAgentTaskId && !detachedRootTaskId ? initialAgentTaskId : null,
    hydrateChainRootId: detachedRootTaskId,
  };
}
