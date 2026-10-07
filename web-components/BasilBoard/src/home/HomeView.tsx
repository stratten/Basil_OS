import { useCallback, useEffect, useState } from 'react';
import type { BoardInquirySummary } from '../contracts';
import { hydrateBasilBoard, submitHomeTurn } from '../services/api';
import { enqueueAgentTaskOriginNavigation, showAgentTaskFromHome } from '../services/bridge';
import { basilBoardWebSocket } from '../services/websocket';
import HomeComposer, { type HomeComposerSubmission } from './HomeComposer';
import { useHomeForward } from './HomeForwardContext';
import { homeErrorMessage } from './homeErrorMessage';
import { isTerminalAgentTaskEvent } from './homeReducer';
import { useHomeRuntime } from './HomeRuntimeContext';
import RecentRequests from './RecentRequests';

export const HOME_ROUTING_STATUS = 'Working out where this goes...';

export default function HomeView() {
  const { voiceError, voiceState, voiceTurn } = useHomeRuntime();
  const forward = useHomeForward();
  const [inquiries, setInquiries] = useState<BoardInquirySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | undefined>();

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(undefined);
    try {
      const hydration = await hydrateBasilBoard();
      setInquiries(hydration.recent_inquiries);
    } catch (error) {
      setLoadError(homeErrorMessage(error, 'Failed to load Home'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const voiceTurnVersion = voiceTurn?.version ?? 0;
  useEffect(() => {
    if (voiceTurnVersion > 0) void refresh();
  }, [refresh, voiceTurnVersion]);

  useEffect(() => {
    return basilBoardWebSocket.subscribe((event) => {
      if (isTerminalAgentTaskEvent(event)) void refresh();
    });
  }, [refresh]);

  async function handleSubmit(submission: HomeComposerSubmission) {
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const response = await submitHomeTurn(submission);
      if (!forward) throw new Error('Home cannot open the destination from this window.');
      forward.forwardTurn(response, submission);
      void refresh();
    } catch (error) {
      setSubmitError(homeErrorMessage(error, 'Failed to submit turn'));
      throw error;
    } finally {
      setSubmitting(false);
    }
  }

  function openInquiry(inquiry: BoardInquirySummary) {
    if (inquiry.routeKind === 'conversation' && inquiry.conversationId) {
      enqueueAgentTaskOriginNavigation({ originType: 'conversation', originId: inquiry.conversationId });
    } else if (inquiry.routeKind === 'agent_task' && inquiry.agentTaskId) {
      showAgentTaskFromHome(inquiry.agentTaskId);
    }
  }

  return (
    <section className="home-view home-front-door">
      <div className="home-front-door-column">
        <h1 className="home-front-door-title">What can Basil do for you?</h1>
        <p className="home-front-door-hint">
          Ask a question or hand over a task. I'll open a chat or start an agent for you.
        </p>
        <HomeComposer
          disabled={submitting}
          voiceState={voiceState}
          statusText={submitting ? HOME_ROUTING_STATUS : undefined}
          onSubmit={handleSubmit}
        />
        {submitError ? <div className="home-inline-error" role="alert">{submitError}</div> : null}
        {voiceError ? <div className="home-inline-error" role="alert">{voiceError}</div> : null}
        <RecentRequests
          inquiries={inquiries}
          loading={loading}
          loadError={loadError}
          onOpen={openInquiry}
          onRetry={() => void refresh()}
        />
      </div>
    </section>
  );
}
