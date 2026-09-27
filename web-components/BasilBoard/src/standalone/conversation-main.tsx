import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import ConversationStandaloneApp from './ConversationStandaloneApp';
import '@agent-task/styles/theme.css';
import { applyProcessingDefaults } from '../theme/agentTaskTheme';
import '../styles/shell.css';
import '../styles/home.css';
import '../styles/chats.css';
import '../styles/chats-messages.css';
import '../styles/chats-output-strip.css';
import '../styles/chats-artifact-sidebar.css';
import '@agent-task/styles/components/artifact-review-workspace.css';

applyProcessingDefaults();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConversationStandaloneApp />
  </StrictMode>,
);
