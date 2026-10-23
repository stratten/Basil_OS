import React from 'react';
import ReactDOM from 'react-dom/client';
import MeetingCompanionApp from '../MeetingCompanionApp';
import '../styles/meeting-assistant.css';
import '../styles/companion.css';
import '../styles/companion-ledger.css';
import '../styles/companion-audit.css';
import '../styles/meeting-assistant-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MeetingCompanionApp />
  </React.StrictMode>,
);
