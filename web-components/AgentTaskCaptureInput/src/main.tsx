import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/theme.css';
import '@shared/reduced-motion.css';
import './styles/capture-widget.css';
import './styles/capture-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
