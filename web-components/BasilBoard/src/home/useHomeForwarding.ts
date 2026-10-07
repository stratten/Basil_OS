import { useCallback, useEffect, useMemo, useState } from 'react';
import type { HomeTurnResponse } from '../contracts';
import { rerouteHomeInquiry } from '../services/api';
import { showAgentTaskFromHome } from '../services/bridge';
import type { HomeComposerSubmission } from './HomeComposer';
import type { HomeChatHandoff, HomeForwardContextValue, RoutedNoticeState } from './HomeForwardContext';
import { homeErrorMessage } from './homeErrorMessage';

export const ROUTED_NOTICE_AUTO_DISMISS_MS = 15_000;
const CHATS_TAB_ID = 'chats';

interface UseHomeForwardingOptions {
  hasTab: (tabId: string) => boolean;
  selectTab: (tabId: string) => void;
}

function createNonce(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? `handoff-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function useHomeForwarding({ hasTab, selectTab }: UseHomeForwardingOptions) {
  const [chatHandoff, setChatHandoff] = useState<HomeChatHandoff>();
  const [notice, setNotice] = useState<RoutedNoticeState>();

  const forwardTurn = useCallback((response: HomeTurnResponse, submission: HomeComposerSubmission) => {
    if (response.route_kind === 'conversation') {
      if (!response.conversation_id) throw new Error('Basil did not return a conversation for this request.');
      setChatHandoff({
        nonce: createNonce(),
        conversationId: response.conversation_id,
        content: submission.content,
        displayMarkdown: submission.displayMarkdown,
        filePaths: submission.referencePaths,
        modelId: submission.modelId,
        createdAt: Date.now(),
      });
      if (hasTab(CHATS_TAB_ID)) selectTab(CHATS_TAB_ID);
    } else {
      if (response.state === 'failed' || !response.agent_task_id) {
        throw new Error('Basil could not start the agent task.');
      }
      setChatHandoff(undefined);
      showAgentTaskFromHome(response.agent_task_id);
    }
    setNotice({
      inquiryId: response.inquiry_id,
      routeKind: response.route_kind,
      submission,
      rerouting: false,
    });
  }, [hasTab, selectTab]);

  const consumeChatHandoff = useCallback((nonce: string) => {
    setChatHandoff((current) => (current?.nonce === nonce ? undefined : current));
  }, []);

  const dismissNotice = useCallback(() => setNotice(undefined), []);

  const reroute = useCallback(async () => {
    if (!notice || notice.rerouting) return;
    const target = notice.routeKind === 'conversation' ? 'agent_task' : 'conversation';
    setNotice({ ...notice, rerouting: true, error: undefined });
    try {
      const response = await rerouteHomeInquiry(notice.inquiryId, target);
      forwardTurn(response, notice.submission);
    } catch (error) {
      const message = homeErrorMessage(error, 'Could not change where this request went.');
      setNotice((current) => (current ? { ...current, rerouting: false, error: message } : current));
    }
  }, [forwardTurn, notice]);

  const [noticeEngaged, setNoticeEngaged] = useState(false);
  const noticeVisible = notice !== undefined;
  useEffect(() => {
    if (!noticeVisible) setNoticeEngaged(false);
  }, [noticeVisible]);
  const settled = Boolean(notice && !notice.rerouting && !notice.error);
  const noticeKey = notice ? `${notice.inquiryId}:${notice.routeKind}` : '';
  useEffect(() => {
    if (!settled || noticeEngaged) return undefined;
    const timer = window.setTimeout(() => setNotice(undefined), ROUTED_NOTICE_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [noticeEngaged, noticeKey, settled]);

  const contextValue = useMemo<HomeForwardContextValue>(
    () => ({ forwardTurn, chatHandoff, consumeChatHandoff }),
    [chatHandoff, consumeChatHandoff, forwardTurn],
  );

  return { contextValue, notice, dismissNotice, reroute, setNoticeEngaged };
}
