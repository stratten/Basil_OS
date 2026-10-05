import React from 'react';
import ReactDOM from 'react-dom/client';
import MeetingAnalysisApp from '../MeetingAnalysisApp';
import '../styles/meeting-analysis.css';
import '../styles/meeting-analysis-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MeetingAnalysisApp />
  </React.StrictMode>,
);
