import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import InquiryDetail from './InquiryDetail';

const mocks = vi.hoisted(() => ({
  getBoardInquiry: vi.fn(),
}));

vi.mock('../services/api', () => ({
  getBoardInquiry: mocks.getBoardInquiry,
}));

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: {
    subscribe: () => () => {},
  },
}));

vi.mock('../services/bridge', () => ({
  openExistingAgentTaskWidget: vi.fn(),
}));

describe('InquiryDetail', () => {
  it('retries a failed inquiry load', async () => {
    mocks.getBoardInquiry
      .mockRejectedValueOnce(new Error('Inquiry unavailable'))
      .mockResolvedValueOnce({ timeline: [] });

    render(<InquiryDetail inquiryId="inquiry-1" />);

    expect(await screen.findByText('Inquiry unavailable')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(mocks.getBoardInquiry).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText('This inquiry has no content.')).toBeTruthy();
  });
});
