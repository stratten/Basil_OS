import { createContext, useContext } from 'react';
import type { HomeTurnResponse, HomeVoiceCaptureState } from '../contracts';
import type { HomeComposerSubmission } from './HomeComposer';

export interface HomeVoiceTurn {
  version: number;
  response: HomeTurnResponse;
  submission: HomeComposerSubmission;
}

export interface HomeRuntime {
  voiceState: HomeVoiceCaptureState;
  voiceError?: string;
  voiceTurn?: HomeVoiceTurn;
  statusIconDataUrl?: string;
}

export const HomeRuntimeContext = createContext<HomeRuntime>({
  voiceState: 'idle',
});

export function useHomeRuntime(): HomeRuntime {
  return useContext(HomeRuntimeContext);
}
