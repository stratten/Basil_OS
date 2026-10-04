import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/theme.css';
import '@shared/reduced-motion.css';
import './styles/components.css';
import './styles/reconciliation-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';

enableBackdropSurfaceFinish();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
