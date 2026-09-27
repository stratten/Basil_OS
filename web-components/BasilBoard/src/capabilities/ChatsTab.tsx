import { useEffect, useState } from 'react';
import type { AgentTaskOriginNavigationPayload, BoardConversationAvailability } from '../contracts';
import {
  activateBoardConversationSurface,
  deactivateBoardConversationSurface,
  registerBoardConversationAvailabilityHandler,
  registerDetachedConversationsChangedHandler,
} from '../services/bridge';
import ConversationWorkspace from './ConversationWorkspace';

interface ChatsTabProps {
  originNavigation?: AgentTaskOriginNavigationPayload;
}

export default function ChatsTab({ originNavigation }: ChatsTabProps) {
  const [availability, setAvailability] = useState<BoardConversationAvailability>('available');
  // Ids of conversations open in their own detached window. Unlike
  // `availability` above (which only covers the legacy global Conversation
  // widget and hides this entire tab), this is scoped per-conversation: the
  // sidebar and any other conversation stay fully usable, and only the
  // specific detached conversation's content area is replaced with a
  // placeholder. Mirrors the Agent Task tab's per-root detached handling.
  const [detachedConversationIds, setDetachedConversationIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const unregisterAvailability = registerBoardConversationAvailabilityHandler((payload) => {
      setAvailability(payload.availability);
    });
    const unregisterDetached = registerDetachedConversationsChangedHandler((payload) => {
      setDetachedConversationIds(new Set(payload.conversationIds));
    });
    activateBoardConversationSurface();
    return () => {
      deactivateBoardConversationSurface();
      unregisterAvailability();
      unregisterDetached();
    };
  }, []);

  if (availability === 'unavailable') {
    return (
      <div className="home-unavailable-state basil-board-detached-placeholder" role="status">
        <p>Conversation is open in a separate window.</p>
        <p>Close that window to view Conversation here.</p>
      </div>
    );
  }

  return <ConversationWorkspace originNavigation={originNavigation} detachedConversationIds={detachedConversationIds} />;
}
