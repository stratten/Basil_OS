import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionProposalSettings from './CompanionProposalSettings';
import type { CompanionGlobalSettings } from './types';

function settings(overrides: Partial<CompanionGlobalSettings> = {}): CompanionGlobalSettings {
  return {
    auto_enable: false,
    default_mode: 'active',
    next_focus: '',
    screen_share_note_dismissed: true,
    proposal_mode: 'suggestion_only',
    proposal_capabilities: ['todo', 'agent_task', 'assistant_session'],
    auto_execute_capabilities: [],
    ...overrides,
  };
}

describe('CompanionProposalSettings', () => {
  it('renders nothing until the settings have loaded', () => {
    const { container } = render(<CompanionProposalSettings settings={null} update={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('starts off, says nothing starts without approval, and shows no per-kind switches', () => {
    render(<CompanionProposalSettings settings={settings()} update={vi.fn()} />);
    expect(screen.getByLabelText('Let my watches start actions without asking')).not.toBeChecked();
    expect(screen.getByText('The Companion proposes follow-ups as cards. Nothing starts until you approve it.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Add To-Dos')).toBeNull();
  });

  it('turns automatic starts on without choosing any kind for the user', async () => {
    const update = vi.fn(async () => true);
    render(<CompanionProposalSettings settings={settings()} update={update} />);
    fireEvent.click(screen.getByLabelText('Let my watches start actions without asking'));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ proposal_mode: 'auto_execute' }));
  });

  it('asks the user to choose kinds while none is chosen', () => {
    render(<CompanionProposalSettings settings={settings({ proposal_mode: 'auto_execute' })} update={vi.fn()} />);
    expect(screen.getByLabelText('Add To-Dos')).not.toBeChecked();
    expect(screen.getByLabelText('Start Agent Tasks')).not.toBeChecked();
    expect(screen.getByText(/Choose which kinds of action may start by themselves/)).toBeInTheDocument();
  });

  it('adds and removes one kind at a time and keeps the others', async () => {
    const update = vi.fn(async () => true);
    const { rerender } = render(<CompanionProposalSettings settings={settings({ proposal_mode: 'auto_execute' })} update={update} />);
    fireEvent.click(screen.getByLabelText('Add To-Dos'));
    await waitFor(() => expect(update).toHaveBeenLastCalledWith({ auto_execute_capabilities: ['todo'] }));
    rerender(<CompanionProposalSettings settings={settings({ proposal_mode: 'auto_execute', auto_execute_capabilities: ['todo', 'agent_task'] })} update={update} />);
    expect(screen.getByText(/Only a watch you created can start something/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Add To-Dos'));
    await waitFor(() => expect(update).toHaveBeenLastCalledWith({ auto_execute_capabilities: ['agent_task'] }));
  });

  it('turns automatic starts back off', async () => {
    const update = vi.fn(async () => true);
    render(<CompanionProposalSettings settings={settings({ proposal_mode: 'auto_execute', auto_execute_capabilities: ['todo'] })} update={update} />);
    fireEvent.click(screen.getByLabelText('Let my watches start actions without asking'));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ proposal_mode: 'suggestion_only' }));
  });

  it('says so when a setting could not be saved', async () => {
    render(<CompanionProposalSettings settings={settings()} update={vi.fn(async () => false)} />);
    fireEvent.click(screen.getByLabelText('Let my watches start actions without asking'));
    expect(await screen.findByRole('alert')).toHaveTextContent('That setting could not be saved.');
  });
});
