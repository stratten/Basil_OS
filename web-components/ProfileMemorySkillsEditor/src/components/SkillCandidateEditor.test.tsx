import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProfileEditorApiError } from '../services/api';
import { SkillCandidateEditor } from './SkillCandidateEditor';

const api = vi.hoisted(() => ({
  approveSkillCandidate: vi.fn(),
  declineSkillCandidate: vi.fn(),
  getAgentTaskSummary: vi.fn(),
  getSkillCandidate: vi.fn(),
}));
const bridge = vi.hoisted(() => ({
  notifyDeclined: vi.fn(),
  notifySaved: vi.fn(),
  openSourceTask: vi.fn(),
}));

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  ...api,
}));
vi.mock('../services/bridge', () => bridge);

const candidate = {
  id: 'candidate-1',
  title: 'Inspect PDF',
  when_to_use: 'Use when inspecting a PDF.',
  triggers: ['pdf', 'review'],
  procedure_markdown: 'Review the PDF carefully.',
  expected_result: 'A verified PDF result.',
  source_task_ids: [],
  source: 'test',
  created_at: '2026-08-18T00:00:00Z',
  status: 'pending',
  observation_count: 1,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SkillCandidateEditor', () => {
  it('disables controls while loading and sends one approval for rapid clicks', async () => {
    const loaded = deferred<typeof candidate | null>();
    const approval = deferred<typeof candidate>();
    api.getSkillCandidate.mockReturnValue(loaded.promise);
    api.approveSkillCandidate.mockReturnValue(approval.promise);

    render(<SkillCandidateEditor apiBaseUrl="http://localhost" candidateId={candidate.id} />);

    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled();

    loaded.resolve(candidate);
    expect(await screen.findByDisplayValue(candidate.title)).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    fireEvent.click(screen.getByRole('button', { name: 'Approving…' }));

    expect(api.approveSkillCandidate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled();

    approval.resolve(candidate);
    await waitFor(() => expect(bridge.notifySaved).toHaveBeenCalledWith(true));
    expect(bridge.notifySaved).toHaveBeenCalledTimes(1);
  });

  it('prevents duplicate declines and restores controls after an error', async () => {
    const decline = deferred<typeof candidate>();
    api.getSkillCandidate.mockResolvedValue(candidate);
    api.declineSkillCandidate.mockReturnValue(decline.promise);

    render(<SkillCandidateEditor apiBaseUrl="http://localhost" candidateId={candidate.id} />);

    await screen.findByDisplayValue(candidate.title);
    fireEvent.click(screen.getByRole('button', { name: 'Decline' }));
    fireEvent.click(screen.getByRole('button', { name: 'Declining…' }));

    expect(api.declineSkillCandidate).toHaveBeenCalledTimes(1);
    decline.reject(new ProfileEditorApiError(409, 'Skill changes are locked while reconciliation is active.'));

    expect(await screen.findByText('Skill changes are locked while reconciliation is active.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeEnabled();
    expect(bridge.notifyDeclined).not.toHaveBeenCalled();
  });

  it('keeps approve and decline disabled after the initial candidate fetch fails', async () => {
    api.getSkillCandidate.mockRejectedValue(new Error('Skill candidate not found'));

    render(<SkillCandidateEditor apiBaseUrl="http://localhost" candidateId={candidate.id} />);

    expect(await screen.findByText('Skill candidate not found')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    fireEvent.click(screen.getByRole('button', { name: 'Decline' }));

    expect(api.approveSkillCandidate).not.toHaveBeenCalled();
    expect(api.declineSkillCandidate).not.toHaveBeenCalled();
  });
});
