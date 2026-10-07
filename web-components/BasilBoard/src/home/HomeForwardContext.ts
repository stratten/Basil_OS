import { createContext, useContext } from 'react';
import type { HomeTurnResponse } from '../contracts';
import type { HomeComposerSubmission } from './HomeComposer';

export interface HomeChatHandoff {
  nonce: string;
  conversationId: string;
  content: string;
  displayMarkdown: string;
  filePaths: string[];
  modelId?: string;
  createdAt: number;
}

export type HomeRouteTarget = 'conversation' | 'agent_task';

export interface RoutedNoticeState {
  inquiryId: string;
  routeKind: HomeRouteTarget;
  submission: HomeComposerSubmission;
  rerouting: boolean;
  error?: string;
}

export interface HomeForwardContextValue {
  forwardTurn: (response: HomeTurnResponse, submission: HomeComposerSubmission) => void;
  chatHandoff?: HomeChatHandoff;
  consumeChatHandoff: (nonce: string) => void;
}

export const HOME_CHAT_HANDOFF_MAX_AGE_MS = 60_000;

export const HomeForwardContext = createContext<HomeForwardContextValue | null>(null);

export function useHomeForward(): HomeForwardContextValue | null {
  return useContext(HomeForwardContext);
}
