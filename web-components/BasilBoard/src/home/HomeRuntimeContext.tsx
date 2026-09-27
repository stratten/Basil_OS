import { createContext, useContext } from 'react';
import type { HomeVoiceCaptureState } from '../contracts';

export interface HomeRuntime {
  voiceState: HomeVoiceCaptureState;
  voiceError?: string;
  voiceTurnVersion: number;
  statusIconDataUrl?: string;
}

export const HomeRuntimeContext = createContext<HomeRuntime>({
  voiceState: 'idle',
  voiceTurnVersion: 0,
});

export function useHomeRuntime(): HomeRuntime {
  return useContext(HomeRuntimeContext);
}
