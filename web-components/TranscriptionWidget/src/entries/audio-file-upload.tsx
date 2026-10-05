import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AudioFileUploadApp } from '../app/AudioFileUploadApp';
import '@shared/reduced-motion.css';
import '../styles/audio-file-upload.css';
import '../styles/audio-file-upload-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

const container = document.getElementById('root');
if (!container) {
  throw new Error('audio-file-upload entry: #root not found');
}
createRoot(container).render(
  <StrictMode>
    <AudioFileUploadApp />
  </StrictMode>,
);
