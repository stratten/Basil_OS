import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AssistantSessionApp } from '../app/AssistantSessionApp';
import '../styles/assistant-session.css';
import '../styles/assistant-session-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

const container = document.getElementById('root');
if (!container) {
  throw new Error('assistant-session entry: #root not found');
}
createRoot(container).render(
  <StrictMode>
    <AssistantSessionApp />
  </StrictMode>,
);
