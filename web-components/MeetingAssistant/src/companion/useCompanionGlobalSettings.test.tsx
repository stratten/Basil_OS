import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchGlobalSettings: vi.fn(), updateGlobalSettings: vi.fn() }));
vi.mock('./companionApi', () => api);

import { useCompanionGlobalSettings } from './useCompanionGlobalSettings';

const saved = { auto_enable: false, default_mode: 'active', screen_share_note_dismissed: false };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useCompanionGlobalSettings', () => {
  it('loads once, applies a patch immediately and keeps it when the save succeeds', async () => {
    api.fetchGlobalSettings.mockResolvedValue(saved);
    api.updateGlobalSettings.mockResolvedValue({ ...saved, auto_enable: true });
    const { result } = renderHook(() => useCompanionGlobalSettings(8123));
    await waitFor(() => expect(result.current.settings).toEqual(saved));
    let accepted = false;
    await act(async () => {
      accepted = await result.current.update({ auto_enable: true });
    });
    expect(accepted).toBe(true);
    expect(result.current.settings?.auto_enable).toBe(true);
    expect(api.fetchGlobalSettings).toHaveBeenCalledTimes(1);
    expect(api.updateGlobalSettings).toHaveBeenCalledWith(8123, { auto_enable: true });
  });

  it('restores the previous settings when the save fails', async () => {
    api.fetchGlobalSettings.mockResolvedValue(saved);
    api.updateGlobalSettings.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useCompanionGlobalSettings(8123));
    await waitFor(() => expect(result.current.settings).toEqual(saved));
    let accepted = true;
    await act(async () => {
      accepted = await result.current.update({ auto_enable: true });
    });
    expect(accepted).toBe(false);
    expect(result.current.settings).toEqual(saved);
  });

  it('stays empty and refuses updates without a port or after a failed load', async () => {
    const noPort = renderHook(() => useCompanionGlobalSettings(0));
    expect(noPort.result.current.settings).toBeNull();
    let accepted = true;
    await act(async () => {
      accepted = await noPort.result.current.update({ auto_enable: true });
    });
    expect(accepted).toBe(false);
    expect(api.fetchGlobalSettings).not.toHaveBeenCalled();

    api.fetchGlobalSettings.mockRejectedValue(new Error('down'));
    const failed = renderHook(() => useCompanionGlobalSettings(8123));
    await waitFor(() => expect(api.fetchGlobalSettings).toHaveBeenCalledTimes(1));
    expect(failed.result.current.settings).toBeNull();
    expect(api.updateGlobalSettings).not.toHaveBeenCalled();
  });
});
