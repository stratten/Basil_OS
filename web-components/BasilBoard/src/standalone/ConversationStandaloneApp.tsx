import { useEffect, useState } from 'react';
import type { AgentTaskOriginNavigationPayload, BasilBoardInitPayload } from '../contracts';
import { configureApiBaseUrl, websocketUrl } from '../services/api';
import { basilBoardWebSocket } from '../services/websocket';
import {
  notifyReady,
  registerAgentTaskOriginNavigationHandler,
  registerBridgeHandlers,
  registerDetachedConversationsChangedHandler,
} from '../services/bridge';
import { applyHostFonts, applyHostTheme } from '../theme/agentTaskTheme';
import ConversationWorkspace from '../capabilities/ConversationWorkspace';
import ConversationWindowChrome from './ConversationWindowChrome';

export default function ConversationStandaloneApp() {
  const [initialized, setInitialized] = useState(false);
  const [conversationSubtitle, setConversationSubtitle] = useState<string>();
  const [initialConversationId, setInitialConversationId] = useState<string>();
  const [conversationPresentation, setConversationPresentation] = useState<'global' | 'thread'>('global');
  const [originNavigation, setOriginNavigation] = useState<AgentTaskOriginNavigationPayload>();
  const [detachedConversationIds, setDetachedConversationIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    registerBridgeHandlers({
      onInit: (payload: BasilBoardInitPayload) => {
        if (payload.apiBaseUrl) {
          configureApiBaseUrl(payload.apiBaseUrl);
        }
        applyHostTheme(payload.theme);
        applyHostFonts(payload.fonts);
        setInitialConversationId(payload.initialConversationId);
        setConversationPresentation(payload.conversationPresentation ?? 'global');
        setInitialized(true);
      },
      // The standalone Conversation window never emits Home voice-turn or status-icon bridge messages; these satisfy the shared registration contract.
      onVoiceCaptureState: () => {},
      onVoiceCaptureFinished: async () => {},
      onStatusIconChanged: () => {},
    });
    const unregisterOriginNavigation = registerAgentTaskOriginNavigationHandler(setOriginNavigation);
    const unregisterDetachedConversations = registerDetachedConversationsChangedHandler((payload) => {
      setDetachedConversationIds(new Set(payload.conversationIds));
    });
    notifyReady();
    return () => {
      unregisterOriginNavigation();
      unregisterDetachedConversations();
    };
  }, []);

  useEffect(() => {
    if (!initialized) return;
    basilBoardWebSocket.connect(websocketUrl());
    return () => basilBoardWebSocket.disconnect();
  }, [initialized]);

  if (!initialized) {
    return <div className="home-loading">Waiting for host...</div>;
  }

  return (
    <ConversationWindowChrome subtitle={conversationSubtitle}>
      <ConversationWorkspace
        onConversationSubtitleChange={setConversationSubtitle}
        showConversationHeader={false}
        initialConversationId={initialConversationId}
        conversationPresentation={conversationPresentation}
        originNavigation={originNavigation}
        detachedConversationIds={conversationPresentation === 'global' ? detachedConversationIds : undefined}
      />
    </ConversationWindowChrome>
  );
}
