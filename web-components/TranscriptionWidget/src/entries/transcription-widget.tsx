import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { TranscriptionWidgetApp } from '../app/TranscriptionWidgetApp';
import '@shared/reduced-motion.css';
import '../styles/transcription-widget.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('transcription-widget entry: #root not found');
}
createRoot(container).render(
  <StrictMode>
    <TranscriptionWidgetApp />
  </StrictMode>,
);
