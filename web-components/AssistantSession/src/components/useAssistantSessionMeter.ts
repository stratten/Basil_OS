import { useEffect, useState } from 'react';
import { onAssistantSessionMeter } from '../bridge/assistantSessionBridge';

/** Subscribes to the high-frequency meter channel locally so audio-level ticks only re-render this hook's caller (Header), not the whole AssistantSessionApp tree. */
export function useAssistantSessionMeter(): number {
  const [meterLevel, setMeterLevel] = useState(0);
  useEffect(() => onAssistantSessionMeter(setMeterLevel), []);
  return meterLevel;
}
