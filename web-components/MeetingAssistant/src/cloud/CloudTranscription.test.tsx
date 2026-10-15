import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cloudState } from './cloudTestFixtures';
import type { CloudTranscriptionState } from './cloudTranscriptionTypes';

const hoisted = vi.hoisted(() => ({
  controller: null as unknown as Record<string, unknown>,
  lastPort: -1,
}));

vi.mock('./useCloudTranscription', () => ({
  useCloudTranscription: (port: number) => {
    hoisted.lastPort = port;
    return hoisted.controller;
  },
}));

import CloudTranscription from './CloudTranscription';

function controller(state: CloudTranscriptionState | null, overrides: Record<string, unknown> = {}) {
  hoisted.controller = {
    state,
    loadError: null,
    actionError: null,
    busy: false,
    checkResult: null,
    update: vi.fn(() => Promise.resolve(true)),
    saveKey: vi.fn(() => Promise.resolve(true)),
    removeKey: vi.fn(() => Promise.resolve(true)),
    check: vi.fn(() => Promise.resolve()),
    retry: vi.fn(() => Promise.resolve()),
    ...overrides,
  };
  return hoisted.controller as {
    update: ReturnType<typeof vi.fn>;
    saveKey: ReturnType<typeof vi.fn>;
    removeKey: ReturnType<typeof vi.fn>;
    check: ReturnType<typeof vi.fn>;
    retry: ReturnType<typeof vi.fn>;
  };
}

function open() {
  fireEvent.click(screen.getByRole('button', { name: /Cloud transcription/ }));
}

beforeEach(() => {
  hoisted.lastPort = -1;
});

describe('CloudTranscription', () => {
  it('renders nothing without a backend port', () => {
    controller(cloudState());
    const { container } = render(<CloudTranscription port={0} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a collapsed chip that reflects the state and expands and collapses', () => {
    controller(cloudState({ enabled: true, acknowledged: true, status: { state: 'streaming', provider: 'deepgram', tier: 'streaming', reason: null } }));
    render(<CloudTranscription port={8123} />);
    expect(hoisted.lastPort).toBe(8123);
    const chip = screen.getByRole('button', { name: 'Cloud transcription: Deepgram' });
    expect(chip).toHaveAttribute('aria-expanded', 'false');
    expect(chip.className).toContain('meeting-cloud-chip--streaming');
    expect(screen.queryByRole('group', { name: 'Cloud transcription settings' })).toBeNull();
    fireEvent.click(chip);
    expect(chip).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('group', { name: 'Cloud transcription settings' })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('group', { name: 'Cloud transcription settings' }), { key: 'Escape' });
    expect(screen.queryByRole('group', { name: 'Cloud transcription settings' })).toBeNull();
  });

  it('shows loading, then a load error with a retry', () => {
    controller(null);
    const { unmount } = render(<CloudTranscription port={8123} />);
    open();
    expect(screen.getByRole('status')).toHaveTextContent('Loading cloud transcription settings.');
    unmount();
    const failing = controller(null, { loadError: 'Could not load the cloud transcription settings.' });
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the cloud transcription settings.');
    fireEvent.click(screen.getByRole('button', { name: 'Try Again' }));
    expect(failing.retry).toHaveBeenCalled();
  });

  it('keeps the switch off until the disclosure is confirmed, then turns it on with the acknowledgment', () => {
    const api = controller(cloudState({ providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] }));
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.getByText(/live meeting audio is sent to the service you choose/)).toBeInTheDocument();
    const toggle = screen.getByRole('checkbox', { name: 'Use cloud transcription' });
    expect(toggle).toBeDisabled();
    expect(screen.getByText('Confirm the statement above to turn this on.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /I understand that live meeting audio will be sent/ }));
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    expect(api.update).toHaveBeenCalledWith({ enabled: true, acknowledge_disclosure: true });
  });

  it('skips the confirmation once it was acknowledged and can turn the switch off without it', () => {
    const api = controller(cloudState({ enabled: true, acknowledged: true }));
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.queryByRole('checkbox', { name: /I understand/ })).toBeNull();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Use cloud transcription' }));
    expect(api.update).toHaveBeenCalledWith({ enabled: false });
  });

  it('chooses the connection and the service', () => {
    const api = controller(cloudState({ acknowledged: true }));
    render(<CloudTranscription port={8123} />);
    open();
    fireEvent.click(screen.getByRole('radio', { name: /AssemblyAI/ }));
    expect(api.update).toHaveBeenCalledWith({ provider: 'assemblyai' });
    fireEvent.click(screen.getByRole('radio', { name: /My Basil account/ }));
    expect(api.update).toHaveBeenCalledWith({ connection: 'basil_account' });
  });

  it('hides the key controls and explains sign-in for the account connection', () => {
    controller(cloudState({ connection: 'basil_account', acknowledged: true, account_available: false }));
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.queryByLabelText('Deepgram API key')).toBeNull();
    expect(screen.getByText('Sign in to Basil to use your account.')).toBeInTheDocument();
  });

  it('saves a trimmed key, clears the field and never echoes it', () => {
    const api = controller(cloudState({ acknowledged: true }));
    render(<CloudTranscription port={8123} />);
    open();
    const input = screen.getByLabelText('Deepgram API key') as HTMLInputElement;
    expect(input.type).toBe('password');
    const save = screen.getByRole('button', { name: 'Save Key' });
    expect(save).toBeDisabled();
    fireEvent.change(input, { target: { value: 'short' } });
    expect(save).toBeDisabled();
    fireEvent.change(input, { target: { value: '  dg-key-123456  ' } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    expect(api.saveKey).toHaveBeenCalledWith('deepgram', 'dg-key-123456');
  });

  it('tests and removes a saved key, and shows the check result', () => {
    const api = controller(
      cloudState({ acknowledged: true, providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] }),
      { checkResult: { ok: false, message: 'Deepgram rejected the API key.' } },
    );
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.getByRole('radio', { name: 'Deepgram (key saved)' })).toBeChecked();
    expect(screen.getByRole('status')).toHaveTextContent('Deepgram rejected the API key.');
    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));
    expect(api.check).toHaveBeenCalledWith('deepgram');
    fireEvent.click(screen.getByRole('button', { name: 'Remove Key' }));
    expect(api.removeKey).toHaveBeenCalledWith('deepgram');
  });

  it('disables test and remove when no key is saved for the selected service', () => {
    controller(cloudState({ acknowledged: true }));
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.getByRole('button', { name: 'Test Connection' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove Key' })).toBeDisabled();
  });

  it('shows why the local model took over and any action error', () => {
    controller(
      cloudState({ enabled: true, acknowledged: true, status: { state: 'fallback', provider: 'deepgram', tier: 'streaming', reason: 'Deepgram rejected the API key.' } }),
      { actionError: 'Add a Deepgram API key first.' },
    );
    render(<CloudTranscription port={8123} />);
    expect(screen.getByRole('button', { name: 'Cloud transcription failed, using local' }).className).toContain('meeting-cloud-chip--fallback');
    open();
    expect(screen.getByText('Deepgram rejected the API key. The local model is transcribing instead.')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Add a Deepgram API key first.');
  });

  it('locks the controls while a request is running', () => {
    controller(cloudState({ enabled: true, acknowledged: true }), { busy: true });
    render(<CloudTranscription port={8123} />);
    open();
    expect(screen.getByRole('checkbox', { name: 'Use cloud transcription' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: /AssemblyAI/ })).toBeDisabled();
  });
});
