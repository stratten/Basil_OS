import { useCallback, useEffect, useRef, useState } from 'react';
import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import { dismissResourceAdvice, fetchResourceAdvice, reportThermalState, resourceAdviceSocketUrl } from './resourceAdviceApi';
import {
  EMPTY_RESOURCE_ADVICE,
  THERMAL_REPORT_INTERVAL_MS,
  parseResourceAdviceState,
  parseThermalState,
  type ResourceAdviceState,
} from './resourceAdviceTypes';

interface ResourceAdviceOptions {
  /** Backend port; 0 or less means unavailable. */
  port: number;
  /** True only while a recording is live. */
  recording: boolean;
  /** The raw thermal state the desktop client reports; unknown values are ignored. */
  thermalState: string | null | undefined;
}

export function useResourceAdvice({ port, recording, thermalState }: ResourceAdviceOptions) {
  const [state, setState] = useState<ResourceAdviceState>(EMPTY_RESOURCE_ADVICE);
  const revisionRef = useRef(0);
  const active = recording && port > 0;

  const replace = useCallback((next: ResourceAdviceState) => {
    revisionRef.current = next.revision;
    setState(next);
  }, []);

  useEffect(() => {
    if (!active) {
      revisionRef.current = 0;
      setState(EMPTY_RESOURCE_ADVICE);
      return undefined;
    }
    let current = true;
    const hydrate = async () => {
      try {
        const next = await fetchResourceAdvice(port);
        if (current) replace(next);
      } catch {
        // Advice is optional: when the backend cannot be reached the chip stays hidden.
      }
    };
    const socket = new ReconnectingWebSocket<Record<string, unknown> & { event_type: string }>({ logLabel: '[Resource advice WS]' });
    socket.subscribe((frame) => {
      if (!current || frame.event_type !== 'resource_advice') return;
      const next = parseResourceAdviceState(frame);
      if (next !== null && next.revision > revisionRef.current) replace(next);
    });
    socket.onConnect(() => {
      void hydrate();
    });
    socket.connect(resourceAdviceSocketUrl(port));
    void hydrate();
    return () => {
      current = false;
      socket.disconnect();
    };
  }, [active, port, replace]);

  const reportable = parseThermalState(thermalState);
  useEffect(() => {
    if (!active || reportable === null) return undefined;
    const send = () => {
      void reportThermalState(port, reportable).catch(() => undefined);
    };
    send();
    const timer = window.setInterval(send, THERMAL_REPORT_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, port, reportable]);

  const dismiss = useCallback(
    async (adviceId: string) => {
      if (port <= 0) return;
      try {
        replace(await dismissResourceAdvice(port, adviceId));
      } catch {
        // The advice stays visible; the user can try again.
      }
    },
    [port, replace],
  );

  return { advice: active ? state.advice : EMPTY_RESOURCE_ADVICE.advice, dismiss };
}
