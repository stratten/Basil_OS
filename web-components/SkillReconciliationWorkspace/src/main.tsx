import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/theme.css';
import '@shared/motion/reduced-motion.css';
import './styles/components.css';
import './styles/reconciliation-surface-finish.css';
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
