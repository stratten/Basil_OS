import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AssistantOutputHistoryApp } from '../app/AssistantOutputHistoryApp';
import '../styles/assistant-output-history.css';
import '../styles/assistant-output-history-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBasilTooltips();

const container = document.getElementById('root');
if (!container) {
  throw new Error('assistant-output-history entry: #root not found');
}
createRoot(container).render(
  <StrictMode>
    <AssistantOutputHistoryApp />
  </StrictMode>,
);
