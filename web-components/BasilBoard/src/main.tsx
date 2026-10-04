import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '@agent-task/styles/theme.css';
import { applyProcessingDefaults } from './theme/agentTaskTheme';
import '@shared/presence-motion.css';
import '@shared/collapsible-sidebar.css';
import './styles/shell.css';
import './styles/home.css';
import './styles/home-markdown-blocks.css';
import './styles/chats.css';
import './styles/todos.css';
import './styles/chats-messages.css';
import './styles/chats-output-strip.css';
import './styles/chats-artifact-sidebar.css';
import '@agent-task/styles/components/artifact-review-workspace.css';
import './styles/conversation-surface-finish.css';
import './styles/basil-board-surface-finish.css';
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish';

enableBackdropSurfaceFinish();
applyProcessingDefaults();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
