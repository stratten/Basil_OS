import React from 'react';
import ReactDOM from 'react-dom/client';
import MeetingAssistantApp from '../MeetingAssistantApp';
import '../styles/meeting-assistant.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MeetingAssistantApp />
  </React.StrictMode>,
);
