import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchGlobalSettings, updateGlobalSettings } from './companionApi';
import type { CompanionGlobalSettings } from './types';

export type CompanionGlobalSettingsPatch = Partial<Pick<CompanionGlobalSettings, 'auto_enable' | 'default_mode' | 'screen_share_note_dismissed' | 'next_focus'>>;

export interface CompanionGlobalSettingsController {
  /** The saved global settings, or null while loading, without a backend port, or when the request failed. */
  settings: CompanionGlobalSettings | null;
  /** Applies the patch immediately, saves it, and restores the previous settings when the save fails. Resolves true when the backend accepted it. */
  update: (patch: CompanionGlobalSettingsPatch) => Promise<boolean>;
  /** Reloads the saved settings, for example after the backend consumed `next_focus` when a recording started. */
  refresh: () => Promise<void>;
}

/** One load of `GET /meetings/companion/settings` shared by every control that reads or writes the global Companion preferences. */
export function useCompanionGlobalSettings(port: number): CompanionGlobalSettingsController {
  const [settings, setSettings] = useState<CompanionGlobalSettings | null>(null);
  const settingsRef = useRef<CompanionGlobalSettings | null>(null);
  settingsRef.current = settings;

  const generationRef = useRef(0);
  const refresh = useCallback(async () => {
    const generation = (generationRef.current += 1);
    if (port <= 0) {
      setSettings(null);
      return;
    }
    try {
      const loaded = await fetchGlobalSettings(port);
      if (generationRef.current === generation) setSettings(loaded);
    } catch {
      if (generationRef.current === generation) setSettings(null);
    }
  }, [port]);

  useEffect(() => {
    void refresh();
    return () => {
      generationRef.current += 1;
    };
  }, [refresh]);

  const update = useCallback(
    async (patch: CompanionGlobalSettingsPatch) => {
      const previous = settingsRef.current;
      if (port <= 0 || previous === null) return false;
      setSettings({ ...previous, ...patch });
      try {
        await updateGlobalSettings(port, patch);
        return true;
      } catch {
        setSettings(previous);
        return false;
      }
    },
    [port],
  );

  return { settings, update, refresh };
}
