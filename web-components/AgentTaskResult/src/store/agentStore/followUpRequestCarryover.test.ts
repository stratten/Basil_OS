import { describe, expect, it } from 'vitest';
import { AgentStore } from './websocketHandlers';

function storeWithFollowUp(): AgentStore {
  const store = new AgentStore();
  store.registerAgent('root-1', 'the first request');
  store.beginFollowUpTurn('turn-2', 'root-1');
  store.updateAgentTaskText('root-1', 'the first follow-up request');
  store.updateAgentDisplayPromptMarkdown('root-1', 'the **first** follow-up request, rendered');
  store.setReferencePaths('root-1', ['/tmp/first.pdf']);
  store.setConnectionReferences('root-1', [{ connectionId: 'c1', label: 'Gmail' } as never]);
  store.setResult('root-1', 'first follow-up answer', []);
  return store;
}

describe('the request a new follow-up turn starts with', () => {
  it('is blank for a follow-up added to a chain that already has one, until its own transcription arrives', () => {
    const store = storeWithFollowUp();

    store.beginFollowUpTurn('turn-3', 'root-1');

    const agent = store.getAgent('root-1')!;
    expect(agent.originalPrompt).toBe('');
    expect(agent.displayPromptMarkdown).toBeUndefined();
    expect(agent.referencePaths).toEqual([]);
    expect(agent.connectionReferences).toBeUndefined();
  });

  it('keeps the previous follow-up, rendering and references, in the history', () => {
    const store = storeWithFollowUp();

    store.beginFollowUpTurn('turn-3', 'root-1');

    const history = store.getAgent('root-1')!.agentTaskHistory;
    const previous = history[history.length - 1];
    expect(previous.id).toBe('turn-2');
    expect(previous.agentTaskText).toBe('the first follow-up request');
    expect(previous.displayPromptMarkdown).toBe('the **first** follow-up request, rendered');
    expect(previous.reference_paths).toEqual(['/tmp/first.pdf']);
  });

  it('shows the new transcription, not the previous rendering, once it arrives', () => {
    const store = storeWithFollowUp();
    store.beginFollowUpTurn('turn-3', 'root-1');

    store.updateAgentTaskText('root-1', 'the second follow-up request');

    const agent = store.getAgent('root-1')!;
    expect(agent.originalPrompt).toBe('the second follow-up request');
    expect(agent.displayPromptMarkdown?.trim() || agent.originalPrompt).toBe('the second follow-up request');
  });
});
