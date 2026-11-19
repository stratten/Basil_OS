import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '@shared/motion/reduced-motion.css';
import './styles/panel.css';
import { installBlueprintReveal } from '@shared/blueprint/blueprintController';
import { enableBackdropSurfaceFinish } from '@shared/theme/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBlueprintReveal();
installBasilTooltips();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
