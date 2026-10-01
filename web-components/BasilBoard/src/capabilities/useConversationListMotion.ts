import { useLayoutEffect, useRef, type RefObject } from 'react';
import type { ConversationListItem } from '../contracts';
import { prefersReducedMotion } from './prefersReducedMotion';

const REORDER_DURATION_MS = 320;
const ENTER_DURATION_MS = 240;
const MOTION_EASING = 'cubic-bezier(0.2, 0.8, 0.2, 1)';

/** Animates sidebar rows from their previous position when the conversation order changes. */
export function useConversationListMotion(
  listRef: RefObject<HTMLUListElement>,
  conversations: readonly ConversationListItem[],
): void {
  const previousTopsRef = useRef<Map<string, number> | null>(null);
  const previousOrderKeyRef = useRef('');
  const orderKey = conversations.map((conversation) => conversation.id).join('\n');

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) {
      previousTopsRef.current = null;
      previousOrderKeyRef.current = '';
      return;
    }
    const rows = Array.from(list.children).filter(
      (child): child is HTMLElement => child instanceof HTMLElement && Boolean(child.dataset.conversationId),
    );
    const nextTops = new Map(rows.map((row) => [row.dataset.conversationId as string, row.offsetTop]));
    const previousTops = previousTopsRef.current;
    const orderChanged = previousOrderKeyRef.current !== orderKey;
    previousTopsRef.current = nextTops;
    previousOrderKeyRef.current = orderKey;
    if (!previousTops || !orderChanged || prefersReducedMotion()) return;
    for (const row of rows) {
      if (typeof row.animate !== 'function') continue;
      const id = row.dataset.conversationId as string;
      const previousTop = previousTops.get(id);
      const nextTop = nextTops.get(id) ?? 0;
      if (previousTop === undefined) {
        row.animate(
          [{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'translateY(0)' }],
          { duration: ENTER_DURATION_MS, easing: MOTION_EASING },
        );
      } else if (previousTop !== nextTop) {
        row.animate(
          [{ transform: `translateY(${previousTop - nextTop}px)` }, { transform: 'translateY(0)' }],
          { duration: REORDER_DURATION_MS, easing: MOTION_EASING },
        );
      }
    }
  });
}
