import { useEffect, useState } from 'react';
import type { BackendLivenessState } from './websocket/reconnectingWebSocket';

export interface BackendLivenessSource {
  subscribeLiveness(handler: (state: BackendLivenessState) => void): () => void;
}

/** Tracks whether the backend is answering, as reported by the shared WebSocket client. */
export function useBackendLiveness(source: BackendLivenessSource): BackendLivenessState {
  const [liveness, setLiveness] = useState<BackendLivenessState>('connecting');

  useEffect(() => source.subscribeLiveness(setLiveness), [source]);

  return liveness;
}
