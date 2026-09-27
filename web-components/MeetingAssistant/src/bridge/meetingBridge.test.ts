import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import type { MeetingBridgeEvent } from './types';

describe('meetingBridge', () => {
  beforeEach(() => {
    delete (window as any).webkit;
    vi.resetModules();
  });

  afterEach(() => {
    Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('queues events received before a handler is registered', async () => {
    const bridge = await import('./meetingBridge');
    const event: MeetingBridgeEvent = { type: 'snapshot', revision: 0, selectionGeneration: 0, protocolVersion: 4 };
    window.basilMeetingAssistant!.onEvent(event);

    const received: MeetingBridgeEvent[] = [];
    bridge.registerEventHandler((e) => received.push(e));
    expect(received).toEqual([event]);
  });

  it('posts intents through window.webkit.messageHandlers.meetingBridge when present', async () => {
    const postMessage = vi.fn();
    (window as any).webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    const bridge = await import('./meetingBridge');
    bridge.selectMeeting('meeting-123');
    expect(postMessage).toHaveBeenCalledWith({ type: 'selectMeeting', meetingId: 'meeting-123' });
  });

  it('posts the meeting-page append intent through the WebKit handler', async () => {
    const postMessage = vi.fn();
    (window as any).webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    const bridge = await import('./meetingBridge');

    bridge.loadMoreMeetings();

    expect(postMessage).toHaveBeenCalledWith({ type: 'loadMoreMeetings' });
  });

  it('posts the complete advanced-filter value through the WebKit handler', async () => {
    const postMessage = vi.fn();
    (window as any).webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    const bridge = await import('./meetingBridge');
    const filters = { queryMode: 'and' as const, name: '', nameMode: 'and' as const, purpose: '', purposeMode: 'and' as const, participants: 'Miriam', participantsMode: 'or' as const, transcript: 'opportunity,stage', transcriptMode: 'and' as const, source: '', sourceMode: 'and' as const, startDate: null, endDate: null, processing: 'any' as const, analysis: 'any' as const };

    bridge.setMeetingSearchFilters(filters);

    expect(postMessage).toHaveBeenCalledWith({ type: 'setMeetingSearchFilters', ...filters });
  });

  it('does not throw when no Swift handler is present', async () => {
    const bridge = await import('./meetingBridge');
    expect(() => bridge.reportReady()).not.toThrow();
  });

  it('copies text through the browser Clipboard API without a Swift handler', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const bridge = await import('./meetingBridge');

    bridge.copyText('Meeting analysis');

    expect(writeText).toHaveBeenCalledWith('Meeting analysis');
  });

  it('posts start-now and bulk-promote intents through the WebKit handler', async () => {
    const postMessage = vi.fn();
    (window as any).webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    const bridge = await import('./meetingBridge');
    bridge.startProposalNow('proposal-1');
    bridge.promoteAllProposalsToTodos();
    expect(postMessage).toHaveBeenCalledWith({ type: 'startProposalNow', proposalId: 'proposal-1' });
    expect(postMessage).toHaveBeenCalledWith({ type: 'promoteAllProposalsToTodos' });
  });

  it('posts linked To-Do and Agent Task navigation intents through the WebKit handler', async () => {
    const postMessage = vi.fn();
    (window as any).webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    const bridge = await import('./meetingBridge');

    bridge.openProposalTodo('todo-1');
    bridge.openProposalAgentTask('agent-1');

    expect(postMessage).toHaveBeenCalledWith({ type: 'openProposalTodo', todoId: 'todo-1' });
    expect(postMessage).toHaveBeenCalledWith({ type: 'openProposalAgentTask', agentTaskId: 'agent-1' });
  });

  it('delivers events immediately once a handler is registered', async () => {
    const bridge = await import('./meetingBridge');
    const received: MeetingBridgeEvent[] = [];
    bridge.registerEventHandler((e) => received.push(e));
    const event: MeetingBridgeEvent = { type: 'sessionDelta', revision: 1, selectionGeneration: 0, protocolVersion: 4 };
    window.basilMeetingAssistant!.onEvent(event);
    expect(received).toEqual([event]);
  });

  it('publishes incoming meter payloads to React subscribers', async () => {
    const { useMeetingMeter } = await import('./meetingMeterStore');
    await import('./meetingBridge');
    function MeterProbe() {
      const meter = useMeetingMeter();
      return createElement('span', undefined, `${meter.microphoneAudioLevel}:${meter.systemAudioLevel}`);
    }

    render(createElement(MeterProbe));
    await act(async () => {
      window.basilMeetingAssistant!.onMeter({ microphoneAudioLevel: 0.6, systemAudioLevel: 0.2 });
    });

    expect(screen.getByText('0.6:0.2')).toBeInTheDocument();
  });
});
