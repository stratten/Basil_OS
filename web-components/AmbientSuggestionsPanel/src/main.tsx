import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '@shared/reduced-motion.css';
import './styles/panel.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
