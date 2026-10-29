import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import FilePreviewApp from '../components/FilePreviewApp';
import '../styles/theme.css';
import '../styles/components.css';
import '../styles/preview-surface-finish.css';
import { installBlueprintReveal } from '@shared/blueprintController';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBlueprintReveal();
installBasilTooltips();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <FilePreviewApp />
  </StrictMode>
);
