import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AgentTaskPresentationSummary } from '../../artifacts/artifactContract';
import { AgentTaskWorkSummary } from './AgentTaskWorkSummary';

const summary = (overrides: Partial<AgentTaskPresentationSummary> = {}): AgentTaskPresentationSummary => ({
  agentTaskId: 'task-1', lifecycle: 'processing', latestActivity: 'Writing report', workflow: { completedSteps: 2, totalSteps: 3 }, artifacts: [], artifactCount: 4, verificationStatus: 'pending', requiresUserAttention: true, delegatedProviderReportCards: [], ...overrides,
});
describe('AgentTaskWorkSummary', () => {
  it('returns no markup without a summary', () => expect(renderToStaticMarkup(<AgentTaskWorkSummary isProcessing={false} />)).toBe(''));
  it('renders every complete summary metric', () => {
    const markup = renderToStaticMarkup(<AgentTaskWorkSummary summary={summary()} isProcessing />);
    for (const text of ['Work summary', 'processing', 'Writing report', '2 of 3 steps', '4', 'pending', 'Required', 'Work in progress']) expect(markup).toContain(text);
    expect(markup).toContain('agent-task-work-summary-verification--pending');
  });
  it('omits an incomplete workflow ratio', () => expect(renderToStaticMarkup(<AgentTaskWorkSummary summary={summary({ workflow: { totalSteps: 3 } })} isProcessing={false} />)).not.toContain('Workflow'));
  it('does not leak error body text', () => {
    const markup = renderToStaticMarkup(<AgentTaskWorkSummary summary={summary()} isProcessing={false} errorMessage="SECRET failure details" />);
    expect(markup).toContain('Task reported an error'); expect(markup).not.toContain('SECRET failure details');
  });
});
