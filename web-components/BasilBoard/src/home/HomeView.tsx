import { useCallback, useEffect, useState } from 'react';
import type { BoardInquirySummary } from '../contracts';
import { hydrateBasilBoard, submitHomeTurn } from '../services/api';
import { basilBoardWebSocket } from '../services/websocket';
import HomeComposer, { type HomeComposerSubmission } from './HomeComposer';
import { isTerminalAgentTaskEvent } from './homeReducer';
import InquiryDetail from './InquiryDetail';
import InquiryHistory from './InquiryHistory';
import { useHomeRuntime } from './HomeRuntimeContext';

export default function HomeView() {
  const { voiceError, voiceState, voiceTurnVersion } = useHomeRuntime();
  const [inquiries, setInquiries] = useState<BoardInquirySummary[]>([]);
  const [selectedInquiryId, setSelectedInquiryId] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | undefined>();

  const refresh = useCallback(async (selectInquiryId?: string) => {
    setLoading(true);
    setLoadError(undefined);
    try {
      const hydration = await hydrateBasilBoard();
      setInquiries(hydration.recent_inquiries);
      setSelectedInquiryId((current) => {
        if (selectInquiryId) return selectInquiryId;
        if (current && hydration.recent_inquiries.some((inquiry) => inquiry.id === current)) {
          return current;
        }
        return hydration.recent_inquiries[0]?.id;
      });
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Failed to load Home');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (voiceTurnVersion > 0) {
      void refresh();
    }
  }, [refresh, voiceTurnVersion]);

  useEffect(() => {
    return basilBoardWebSocket.subscribe((event) => {
      if (isTerminalAgentTaskEvent(event)) {
        void refresh();
      }
    });
  }, [refresh]);

  async function handleSubmit(submission: HomeComposerSubmission) {
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const response = await submitHomeTurn(submission);
      await refresh(response.inquiry_id);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Failed to submit turn');
      throw error;
    } finally {
      setSubmitting(false);
    }
  }

  if (loading && inquiries.length === 0) {
    return <div className="home-loading">Loading Home...</div>;
  }

  if (loadError) {
    return (
      <div className="home-error-state">
        <p>{loadError}</p>
        <button type="button" onClick={() => void refresh()}>Retry</button>
      </div>
    );
  }

  return (
    <section className="home-view home-view-with-history">
      <div className="home-history-pane">
        <InquiryHistory
          inquiries={inquiries}
          selectedInquiryId={selectedInquiryId}
          onSelect={setSelectedInquiryId}
        />
      </div>
      <div className="home-detail-pane">
        {selectedInquiryId ? (
          <InquiryDetail key={selectedInquiryId} inquiryId={selectedInquiryId} />
        ) : (
          <div className="home-empty-state">
            <p>Ask Basil anything to get started.</p>
          </div>
        )}
        {submitError ? <div className="home-inline-error">{submitError}</div> : null}
        {voiceError ? <div className="home-inline-error">{voiceError}</div> : null}
        <HomeComposer disabled={submitting} voiceState={voiceState} onSubmit={handleSubmit} />
      </div>
    </section>
  );
}
