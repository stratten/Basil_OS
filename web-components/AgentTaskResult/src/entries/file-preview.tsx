import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import FilePreviewApp from '../components/FilePreviewApp';
import '../styles/theme.css';
import '../styles/components.css';
import '../styles/preview-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';

enableBackdropSurfaceFinish();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <FilePreviewApp />
  </StrictMode>
);
