import React from 'react';
import ReactDOM from 'react-dom/client';
import MeetingAssistantApp from '../MeetingAssistantApp';
import '../styles/meeting-assistant.css';
import '../styles/meeting-assistant-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MeetingAssistantApp />
  </React.StrictMode>,
);
