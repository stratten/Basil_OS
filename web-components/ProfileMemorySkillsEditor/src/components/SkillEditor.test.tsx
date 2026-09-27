import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProfileEditorApiError } from '../services/api';
import { SkillEditor } from './SkillEditor';

const api = vi.hoisted(() => ({
  deleteSkill: vi.fn(),
  getSkill: vi.fn(),
  updateSkill: vi.fn(),
}));
const bridge = vi.hoisted(() => ({
  notifySaved: vi.fn(),
}));

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  ...api,
}));
vi.mock('../services/bridge', () => bridge);

const skill = {
  slug: 'inspect-pdf',
  title: 'Inspect PDF',
  body: 'Review the PDF carefully.',
  when_to_use: 'Use when inspecting a PDF.',
  triggers: ['pdf'],
  size_bytes: 24,
  cap_bytes: 2048,
  observation_count: 1,
  version: 1,
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
  vi.unstubAllGlobals();
});

describe('SkillEditor', () => {
  it('disables controls while loading and deletes exactly once after confirmation', async () => {
    const loaded = deferred<typeof skill>();
    const deletion = deferred<{ deleted: boolean }>();
    api.getSkill.mockReturnValue(loaded.promise);
    api.deleteSkill.mockReturnValue(deletion.promise);

    render(<SkillEditor apiBaseUrl="http://localhost" slug={skill.slug} />);

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();
    expect(screen.getByText('Loading…')).toBeInTheDocument();

    loaded.resolve(skill);
    expect(await screen.findByDisplayValue(skill.title)).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Delete' }));
    fireEvent.click(screen.getByRole('button', { name: 'Deleting…' }));

    expect(api.deleteSkill).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Deleting…', { selector: '.editor-operation-status' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();

    deletion.resolve({ deleted: true });
    await waitFor(() => expect(bridge.notifySaved).toHaveBeenCalledWith(true));
    expect(bridge.notifySaved).toHaveBeenCalledTimes(1);
  });

  it('restores controls and shows the parsed conflict message after a rejected delete', async () => {
    api.getSkill.mockResolvedValue(skill);
    api.deleteSkill.mockRejectedValue(
      new ProfileEditorApiError(409, 'Skill changes are locked while reconciliation is active.'),
    );

    render(<SkillEditor apiBaseUrl="http://localhost" slug={skill.slug} />);

    await screen.findByDisplayValue(skill.title);
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Delete' }));

    expect(await screen.findByText('Skill changes are locked while reconciliation is active.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled();
    expect(bridge.notifySaved).not.toHaveBeenCalled();
  });

  it('sends no request when delete is cancelled from the in-panel confirmation', async () => {
    api.getSkill.mockResolvedValue(skill);

    render(<SkillEditor apiBaseUrl="http://localhost" slug={skill.slug} />);

    await screen.findByDisplayValue(skill.title);
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.getByText('Delete this saved skill?')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled();
    expect(api.deleteSkill).not.toHaveBeenCalled();
  });

  it('keeps save and delete disabled after the initial skill fetch fails', async () => {
    api.getSkill.mockRejectedValue(new Error('Skill not found'));

    render(<SkillEditor apiBaseUrl="http://localhost" slug={skill.slug} />);

    expect(await screen.findByText('Skill not found')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(api.updateSkill).not.toHaveBeenCalled();
    expect(api.deleteSkill).not.toHaveBeenCalled();
  });
});
