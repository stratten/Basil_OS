import { describe, expect, it } from 'vitest';
import { planDetachedInitHydration } from './detachedInitPlan';

describe('planDetachedInitHydration', () => {
  it('self-hydrates a non-detached window and does not hydrate a chain', () => {
    const plan = planDetachedInitHydration({ initialAgentTaskId: 'task-1' });
    expect(plan.selfHydrateInitialTaskId).toBe('task-1');
    expect(plan.hydrateChainRootId).toBeNull();
  });

  it('hydrates the chain (not the single task) when the detached root equals the initial task id', () => {
    // This is the exact regression: the host commonly passes the same id for
    // both because follow-up state is merged onto the root. The old guard
    // skipped chain hydration on equality, so a terminal multi-turn chain
    // showed only the root.
    const plan = planDetachedInitHydration({
      initialAgentTaskId: 'root-1',
      detachedRootTaskId: 'root-1',
    });
    expect(plan.selfHydrateInitialTaskId).toBeNull();
    expect(plan.hydrateChainRootId).toBe('root-1');
  });

  it('hydrates the chain and skips self-hydration when a live child differs from the root', () => {
    const plan = planDetachedInitHydration({
      initialAgentTaskId: 'child-2',
      detachedRootTaskId: 'root-1',
    });
    expect(plan.selfHydrateInitialTaskId).toBeNull();
    expect(plan.hydrateChainRootId).toBe('root-1');
  });

  it('hydrates the chain for a detached window with no initial task id', () => {
    const plan = planDetachedInitHydration({ detachedRootTaskId: 'root-1' });
    expect(plan.selfHydrateInitialTaskId).toBeNull();
    expect(plan.hydrateChainRootId).toBe('root-1');
  });

  it('plans nothing when neither id is provided', () => {
    const plan = planDetachedInitHydration({});
    expect(plan.selfHydrateInitialTaskId).toBeNull();
    expect(plan.hydrateChainRootId).toBeNull();
  });
});
