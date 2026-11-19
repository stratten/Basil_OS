import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/theme.css';
import '@shared/motion/reduced-motion.css';
import './styles/capture-widget.css';
import './styles/capture-surface-finish.css';
import { installBlueprintReveal } from '@shared/blueprint/blueprintController';
import { enableBackdropSurfaceFinish } from '@shared/theme/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBlueprintReveal({ notReadySelector: '.capture-widget--loading' });
installBasilTooltips();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
