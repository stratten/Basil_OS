import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { TranscriptionWidgetApp } from '../app/TranscriptionWidgetApp';
import '@shared/reduced-motion.css';
import '../styles/transcription-widget.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

const container = document.getElementById('root');
if (!container) {
  throw new Error('transcription-widget entry: #root not found');
}
createRoot(container).render(
  <StrictMode>
    <TranscriptionWidgetApp />
  </StrictMode>,
);
