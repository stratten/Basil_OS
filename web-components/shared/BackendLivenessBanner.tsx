import './backend-liveness-banner.css';
import { useBackendLiveness, type BackendLivenessSource } from './useBackendLiveness';
import type { BackendLivenessState } from './websocket/reconnectingWebSocket';

export const BACKEND_STALE_MESSAGE =
  "Basil's background service isn't responding. It will reconnect automatically if it recovers.";
export const BACKEND_DISCONNECTED_MESSAGE = "Basil's background service is offline. Reconnecting...";

export function BackendLivenessNotice({ liveness }: { liveness: BackendLivenessState }) {
  if (liveness !== 'stale' && liveness !== 'disconnected') return null;

  const isStale = liveness === 'stale';
  return (
    <div
      role="alert"
      className={`backend-liveness-banner backend-liveness-banner--${liveness}`}
      data-liveness={liveness}
    >
      <span className="backend-liveness-banner__marker" aria-hidden="true">
        !
      </span>
      <span className="backend-liveness-banner__text">
        {isStale ? BACKEND_STALE_MESSAGE : BACKEND_DISCONNECTED_MESSAGE}
      </span>
    </div>
  );
}

/** Shows a prominent alert when the backend stops answering or the connection drops. */
export function BackendLivenessBanner({ socket }: { socket: BackendLivenessSource }) {
  const liveness = useBackendLiveness(socket);
  return <BackendLivenessNotice liveness={liveness} />;
}
