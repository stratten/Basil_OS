import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { cloudState } from './cloudTestFixtures';
import CloudTranscription from './CloudTranscription';

const streaming = { state: 'streaming', provider: 'deepgram', tier: 'streaming', reason: null } as const;

describe('CloudTranscription status chip', () => {
  it('renders nothing while the state is still loading', () => {
    const { container } = render(<CloudTranscription state={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when cloud transcription is off', () => {
    const { container } = render(<CloudTranscription state={cloudState()} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('Cloud transcription: off')).toBeNull();
  });

  it('renders nothing when it is on but no recording is using it', () => {
    const { container } = render(<CloudTranscription state={cloudState({ enabled: true, acknowledged: true })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the service name while streaming', () => {
    render(<CloudTranscription state={cloudState({ enabled: true, acknowledged: true, status: streaming })} />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveTextContent('Cloud transcription: Deepgram');
    expect(chip.className).toContain('meeting-cloud-chip--streaming');
  });

  it('shows connecting', () => {
    render(<CloudTranscription state={cloudState({ enabled: true, acknowledged: true, status: { state: 'connecting', provider: 'deepgram', tier: 'streaming', reason: null } })} />);
    expect(screen.getByRole('status')).toHaveTextContent('Cloud transcription: connecting');
    expect(screen.getByRole('status').className).toContain('meeting-cloud-chip--connecting');
  });

  it('shows the failure and exposes why the local model took over', () => {
    render(<CloudTranscription state={cloudState({ enabled: true, acknowledged: true, status: { state: 'fallback', provider: 'deepgram', tier: 'streaming', reason: 'Deepgram rejected the API key.' } })} />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveTextContent('Cloud transcription failed, using local');
    expect(chip.className).toContain('meeting-cloud-chip--fallback');
    expect(chip).toHaveAttribute('title', 'Deepgram rejected the API key. The local model is transcribing instead.');
  });

  it('is not a control: it has no button and no settings panel', () => {
    render(<CloudTranscription state={cloudState({ enabled: true, acknowledged: true, status: streaming })} />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('group', { name: 'Cloud transcription settings' })).toBeNull();
  });
});
