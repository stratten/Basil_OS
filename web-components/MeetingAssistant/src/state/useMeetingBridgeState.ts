import { useEffect, useReducer } from 'react';
import { registerEventHandler, reportReady } from '../bridge/meetingBridge';
import { applyMeetingHostFonts, applyMeetingHostTheme } from '../lib/hostAppearance';
import { applyMeetingBridgeEvent, initialMeetingState } from './meetingReducer';

/** The state every Notetaker web window shares: the reducer fed by native bridge events, the ready handshake, and the host theme and fonts. */
export function useMeetingBridgeState() {
  const [state, dispatch] = useReducer(applyMeetingBridgeEvent, initialMeetingState);

  useEffect(() => {
    registerEventHandler((event) => dispatch(event));
    reportReady();
  }, []);

  useEffect(() => {
    applyMeetingHostTheme(state.theme);
    applyMeetingHostFonts(state.fonts);
  }, [state.theme, state.fonts]);

  return state;
}
