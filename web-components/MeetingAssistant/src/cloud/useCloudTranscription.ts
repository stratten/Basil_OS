import { useCallback, useEffect, useRef, useState } from 'react';
import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import {
  CloudApiError,
  checkCloudProvider,
  cloudTranscriptionSocketUrl,
  deleteCloudKey,
  fetchCloudTranscription,
  saveCloudKey,
  updateCloudSettings,
} from './cloudTranscriptionApi';
import {
  CLOUD_STATUS_EVENT_TYPE,
  parseCloudStatus,
  type CloudCheckResult,
  type CloudProviderId,
  type CloudSettingsPatch,
  type CloudTranscriptionState,
} from './cloudTranscriptionTypes';

const LOAD_ERROR = 'Could not load the cloud transcription settings.';
const GENERIC_ERROR = 'That did not work. Try again.';

export function useCloudTranscription(port: number) {
  const [state, setState] = useState<CloudTranscriptionState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checkResult, setCheckResult] = useState<CloudCheckResult | null>(null);
  const currentRef = useRef(true);

  const hydrate = useCallback(async () => {
    if (port <= 0) return;
    try {
      const next = await fetchCloudTranscription(port);
      if (!currentRef.current) return;
      setState(next);
      setLoadError(null);
    } catch {
      if (currentRef.current) setLoadError(LOAD_ERROR);
    }
  }, [port]);

  useEffect(() => {
    currentRef.current = true;
    if (port <= 0) {
      setState(null);
      return () => {
        currentRef.current = false;
      };
    }
    const socket = new ReconnectingWebSocket<Record<string, unknown> & { event_type: string }>({ logLabel: '[Cloud transcription WS]' });
    socket.subscribe((frame) => {
      if (!currentRef.current || frame.event_type !== CLOUD_STATUS_EVENT_TYPE) return;
      const status = parseCloudStatus(frame);
      if (status !== null) setState((previous) => (previous === null ? previous : { ...previous, status }));
    });
    socket.onConnect(() => {
      void hydrate();
    });
    socket.connect(cloudTranscriptionSocketUrl(port));
    void hydrate();
    return () => {
      currentRef.current = false;
      socket.disconnect();
    };
  }, [port, hydrate]);

  const run = useCallback(async (action: () => Promise<CloudTranscriptionState>): Promise<boolean> => {
    setBusy(true);
    setActionError(null);
    try {
      const next = await action();
      if (currentRef.current) setState(next);
      return true;
    } catch (error) {
      if (currentRef.current) setActionError(error instanceof CloudApiError ? error.message : GENERIC_ERROR);
      return false;
    } finally {
      if (currentRef.current) setBusy(false);
    }
  }, []);

  const update = useCallback((patch: CloudSettingsPatch) => run(() => updateCloudSettings(port, patch)), [port, run]);
  const saveKey = useCallback(
    (provider: CloudProviderId, apiKey: string) => {
      setCheckResult(null);
      return run(() => saveCloudKey(port, provider, apiKey));
    },
    [port, run],
  );
  const removeKey = useCallback(
    (provider: CloudProviderId) => {
      setCheckResult(null);
      return run(() => deleteCloudKey(port, provider));
    },
    [port, run],
  );

  const check = useCallback(
    async (provider: CloudProviderId) => {
      setBusy(true);
      setActionError(null);
      setCheckResult(null);
      try {
        const result = await checkCloudProvider(port, provider);
        if (currentRef.current) setCheckResult(result);
      } catch (error) {
        if (currentRef.current) setActionError(error instanceof CloudApiError ? error.message : GENERIC_ERROR);
      } finally {
        if (currentRef.current) setBusy(false);
      }
    },
    [port],
  );

  return { state, loadError, actionError, busy, checkResult, update, saveKey, removeKey, check, retry: hydrate };
}
