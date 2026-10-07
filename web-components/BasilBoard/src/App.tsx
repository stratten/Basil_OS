import { useEffect, useState } from 'react';
import type {
  AgentTaskOriginNavigationPayload,
  BasilBoardHydration,
  BasilBoardInitPayload,
  HomeVoiceCaptureStatePayload,
} from './contracts';
import { hydrateBasilBoard, configureApiBaseUrl, submitHomeTurn, websocketUrl } from './services/api';
import { basilBoardWebSocket } from './services/websocket';
import {
  notifyReady,
  registerAgentTaskOriginNavigationHandler,
  registerBridgeHandlers,
} from './services/bridge';
import { applyHostFonts, applyHostTheme } from './theme/agentTaskTheme';
import BasilBoardShell from './shell/BasilBoardShell';
import DetachedCapabilityShell from './shell/DetachedCapabilityShell';
import { HomeRuntimeContext, type HomeVoiceTurn } from './home/HomeRuntimeContext';
import { plainTextToDisplayMarkdown } from '../../shared/editorMarkdown';

export default function App() {
  const [initialized, setInitialized] = useState(false);
  const [detachedTabId, setDetachedTabId] = useState<string | undefined>();
  const [hydration, setHydration] = useState<BasilBoardHydration | null>(null);
  const [error, setError] = useState<string | undefined>();
  const [voiceState, setVoiceState] = useState<HomeVoiceCaptureStatePayload['state']>('idle');
  const [voiceError, setVoiceError] = useState<string | undefined>();
  const [voiceTurn, setVoiceTurn] = useState<HomeVoiceTurn>();
  const [statusIconDataUrl, setStatusIconDataUrl] = useState<string | undefined>();
  const [originNavigation, setOriginNavigation] = useState<AgentTaskOriginNavigationPayload>();

  useEffect(() => {
    registerBridgeHandlers({
      onInit: (payload: BasilBoardInitPayload) => {
        if (payload.apiBaseUrl) {
          configureApiBaseUrl(payload.apiBaseUrl);
        }
        applyHostTheme(payload.theme);
        applyHostFonts(payload.fonts);
        if (payload.detachedTabId) {
          setDetachedTabId(payload.detachedTabId);
        }
        setInitialized(true);
      },
      onVoiceCaptureState: (payload) => {
        setVoiceState(payload.state);
        setVoiceError(payload.error);
      },
      onVoiceCaptureFinished: async (payload) => {
        if (payload.error) {
          setVoiceError(payload.error);
          return;
        }
        const transcription = payload.transcription?.trim();
        if (!transcription) return;
        try {
          const submission = {
            content: transcription,
            displayMarkdown: plainTextToDisplayMarkdown(transcription),
            referencePaths: [],
          };
          const response = await submitHomeTurn(submission);
          const refreshed = await hydrateBasilBoard();
          setHydration(refreshed);
          setVoiceError(undefined);
          setVoiceTurn((current) => ({ version: (current?.version ?? 0) + 1, response, submission }));
        } catch (submitError) {
          setVoiceError(submitError instanceof Error ? submitError.message : 'Voice turn failed');
        }
      },
      onStatusIconChanged: (payload) => {
        setStatusIconDataUrl(payload.dataUrl);
      },
    });
    const unregisterOriginNavigation = registerAgentTaskOriginNavigationHandler(setOriginNavigation);
    notifyReady();
    return unregisterOriginNavigation;
  }, []);

  useEffect(() => {
    if (!initialized) return;
    void hydrateBasilBoard()
      .then((payload) => {
        setHydration(payload);
        basilBoardWebSocket.connect(websocketUrl());
      })
      .catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : 'Failed to hydrate BasilBoard');
      });
    return () => basilBoardWebSocket.disconnect();
  }, [initialized]);

  if (!initialized) {
    return <div className="home-loading">Waiting for host...</div>;
  }

  if (error) {
    return <div className="home-error-state">{error}</div>;
  }

  if (!hydration) {
    return <div className="home-loading">Loading BasilBoard...</div>;
  }

  return (
    <HomeRuntimeContext.Provider value={{ voiceState, voiceError, voiceTurn, statusIconDataUrl }}>
      {detachedTabId ? (
        <DetachedCapabilityShell
          tabs={hydration.tabs}
          detachedTabId={detachedTabId}
          originNavigation={originNavigation}
        />
      ) : (
        <BasilBoardShell tabs={hydration.tabs} originNavigation={originNavigation} />
      )}
    </HomeRuntimeContext.Provider>
  );
}
