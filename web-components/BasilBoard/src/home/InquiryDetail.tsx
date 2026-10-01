import { useEffect, useState } from 'react';
import type { HomeTimelineItem } from '../contracts';
import { getBoardInquiry } from '../services/api';
import { applyWsEvent, mergeTimelineItems } from './homeReducer';
import { basilBoardWebSocket } from '../services/websocket';
import HomeTranscript from './HomeTranscript';

interface InquiryDetailProps {
  inquiryId: string;
}

export default function InquiryDetail({ inquiryId }: InquiryDetailProps) {
  const [timeline, setTimeline] = useState<HomeTimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | undefined>();
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    let canceled = false;
    setLoading(true);
    setLoadError(undefined);
    getBoardInquiry(inquiryId)
      .then((detail) => {
        if (!canceled) setTimeline(detail.timeline);
      })
      .catch((error) => {
        if (!canceled) {
          setLoadError(error instanceof Error ? error.message : 'Failed to load inquiry');
        }
      })
      .finally(() => {
        if (!canceled) setLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, [inquiryId, retryVersion]);

  useEffect(() => {
    const unsubscribe = basilBoardWebSocket.subscribe((event) => {
      setTimeline((current) => applyWsEvent({ timeline: current, submitting: false, voiceState: 'idle' }, event).timeline);
    });
    return unsubscribe;
  }, []);

  if (loading) {
    return <div className="home-loading">Loading inquiry...</div>;
  }

  if (loadError) {
    return (
      <div className="home-error-state">
        <p>{loadError}</p>
        <button type="button" onClick={() => setRetryVersion((version) => version + 1)}>Retry</button>
      </div>
    );
  }

  return <HomeTranscript items={mergeTimelineItems([], timeline)} emptyLabel="This inquiry has no content." />;
}
