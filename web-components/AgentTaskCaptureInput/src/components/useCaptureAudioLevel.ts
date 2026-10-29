import { useEffect, useState } from 'react';
import { registerAudioLevelHandler } from '../services/bridge';

export function useCaptureAudioLevel(): number {
  const [audioLevel, setAudioLevel] = useState(0);
  useEffect(() => registerAudioLevelHandler((level) => setAudioLevel(level)), []);
  return audioLevel;
}
