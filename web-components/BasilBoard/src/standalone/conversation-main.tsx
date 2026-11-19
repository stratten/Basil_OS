import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import ConversationStandaloneApp from './ConversationStandaloneApp';
import '@agent-task/styles/theme.css';
import { applyProcessingDefaults } from '../theme/agentTaskTheme';
import '@shared/motion/presence-motion.css';
import '@shared/disclosure/collapsible-sidebar.css';
import '../styles/shell.css';
import '../styles/home.css';
import '../styles/home-markdown-blocks.css';
import '../styles/chats.css';
import '../styles/chats-messages.css';
import '../styles/chats-output-strip.css';
import '../styles/chats-artifact-sidebar.css';
import '@agent-task/styles/components/artifact-review-workspace.css';
import '../styles/conversation-surface-finish.css';
import { installBlueprintReveal } from '@shared/blueprint/blueprintController';
import { enableBackdropSurfaceFinish } from '@shared/theme/surfaceFinish';
import { installBasilTooltips } from '@shared/tooltip/basilTooltip';

enableBackdropSurfaceFinish();
installBlueprintReveal();
installBasilTooltips();
applyProcessingDefaults();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConversationStandaloneApp />
  </StrictMode>,
);
