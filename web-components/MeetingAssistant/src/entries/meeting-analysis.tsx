import React from 'react';
import ReactDOM from 'react-dom/client';
import MeetingAnalysisApp from '../MeetingAnalysisApp';
import '../styles/meeting-analysis.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MeetingAnalysisApp />
  </React.StrictMode>,
);
