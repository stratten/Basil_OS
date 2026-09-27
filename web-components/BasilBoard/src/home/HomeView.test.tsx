import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { WSEvent } from '../contracts';
import { HomeRuntimeContext } from './HomeRuntimeContext';
import HomeView from './HomeView';

const mocks = vi.hoisted(() => ({
  hydrateBasilBoard: vi.fn(),
  submitHomeTurn: vi.fn(),
  eventHandler: undefined as ((event: WSEvent) => void) | undefined,
}));

vi.mock('../services/api', () => ({
  hydrateBasilBoard: mocks.hydrateBasilBoard,
  submitHomeTurn: mocks.submitHomeTurn,
}));

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: {
    subscribe: (handler: (event: WSEvent) => void) => {
      mocks.eventHandler = handler;
      return () => {};
    },
  },
}));

vi.mock('./HomeComposer', () => ({
  default: () => <div>Composer</div>,
}));

vi.mock('./InquiryDetail', () => ({
  default: ({ inquiryId }: { inquiryId: string }) => <div>Detail: {inquiryId}</div>,
}));

describe('HomeView', () => {
  it('clears a selected inquiry that disappears during a terminal refresh', async () => {
    mocks.hydrateBasilBoard
      .mockResolvedValueOnce({
        recent_inquiries: [{
          id: 'inquiry-1',
          promptText: 'Original inquiry',
          routeKind: 'conversation',
          state: 'completed',
          createdAt: '2026-08-02T12:00:00Z',
        }],
      })
      .mockResolvedValueOnce({ recent_inquiries: [] });

    render(
      <HomeRuntimeContext.Provider value={{ voiceState: 'idle', voiceTurnVersion: 0 }}>
        <HomeView />
      </HomeRuntimeContext.Provider>,
    );

    expect(await screen.findByText('Detail: inquiry-1')).toBeTruthy();
    mocks.eventHandler?.({ event_type: 'agent_task_result', agent_task_id: 'task-1' });

    await waitFor(() => {
      expect(screen.getByText('Ask Basil anything to get started.')).toBeTruthy();
    });
  });
});
