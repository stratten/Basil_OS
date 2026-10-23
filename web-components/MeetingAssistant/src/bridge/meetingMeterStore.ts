import { useSyncExternalStore } from 'react';
import type { MeetingMeterPayload } from './types';

let currentMeter: MeetingMeterPayload = { microphoneAudioLevel: 0, systemAudioLevel: 0 };
const listeners = new Set<() => void>();

export function publishMeetingMeter(payload: MeetingMeterPayload) {
  const microphoneAudioLevel = clampMeterLevel(payload.microphoneAudioLevel);
  const systemAudioLevel = clampMeterLevel(payload.systemAudioLevel);
  if (currentMeter.microphoneAudioLevel === microphoneAudioLevel && currentMeter.systemAudioLevel === systemAudioLevel) return;
  currentMeter = { microphoneAudioLevel, systemAudioLevel };
  listeners.forEach((listener) => listener());
}

export function useMeetingMeter(): MeetingMeterPayload {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return currentMeter;
}

function getServerSnapshot() {
  return currentMeter;
}

function clampMeterLevel(level: number) {
  return Math.min(1, Math.max(0, level));
}
