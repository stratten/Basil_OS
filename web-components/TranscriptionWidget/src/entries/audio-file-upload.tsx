import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AudioFileUploadApp } from '../app/AudioFileUploadApp';
import '../styles/audio-file-upload.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('audio-file-upload entry: #root not found');
}
createRoot(container).render(
  <StrictMode>
    <AudioFileUploadApp />
  </StrictMode>,
);
