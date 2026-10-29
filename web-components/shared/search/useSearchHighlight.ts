import { useEffect } from 'react';
import type { RefObject } from 'react';
import type { SearchFocus } from './searchFocusStore';

export const SEARCH_HIGHLIGHT_NAME = 'search-match';
export const SEARCH_SECTION_ATTRIBUTE = 'data-search-section';
const MAX_HIGHLIGHT_RANGES = 300;
const REAPPLY_DELAY_MS = 150;
const SKIPPED_TAGS = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT']);

/** Which elements own a matchable section, and which id owns content that sits outside every owner element. */
export interface SearchHighlightOwners {
  /** Attribute carried by each section element: `data-run-content` for Agent Task turns, `data-message-id` for chat messages. */
  ownerAttribute: string;
  /** Owner of text outside any owner element, such as the live turn that has no card. Omit when nothing lives outside. */
  fallbackOwnerId?: string;
}

interface HighlightRegistry {
  set(name: string, highlight: unknown): void;
  delete(name: string): void;
}

function highlightRegistry(): HighlightRegistry | null {
  if (typeof CSS === 'undefined') return null;
  const registry = (CSS as unknown as { highlights?: HighlightRegistry }).highlights;
  const HighlightCtor = (globalThis as unknown as { Highlight?: unknown }).Highlight;
  return registry && typeof HighlightCtor === 'function' ? registry : null;
}

function owningId(node: Node, owners: SearchHighlightOwners): string | undefined {
  const owner = node.parentElement?.closest<HTMLElement>(`[${owners.ownerAttribute}]`);
  return owner?.getAttribute(owners.ownerAttribute) ?? owners.fallbackOwnerId;
}

/** Build one Range per case-insensitive occurrence of any token inside the text nodes of the matched sections. */
export function collectMatchRanges(
  container: HTMLElement,
  tokens: readonly string[],
  matchedIds: readonly string[],
  owners: SearchHighlightOwners,
): Range[] {
  const needles = Array.from(new Set(tokens.map(token => token.toLowerCase()).filter(token => token.length > 1)));
  if (needles.length === 0 || matchedIds.length === 0) return [];
  const matched = new Set(matchedIds);
  const ranges: Range[] = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node && ranges.length < MAX_HIGHLIGHT_RANGES; node = walker.nextNode()) {
    const text = node.textContent ?? '';
    if (!text.trim()) continue;
    const parent = node.parentElement;
    if (!parent || SKIPPED_TAGS.has(parent.tagName)) continue;
    const owner = owningId(node, owners);
    if (owner === undefined || !matched.has(owner)) continue;
    const lowered = text.toLowerCase();
    for (const needle of needles) {
      let from = lowered.indexOf(needle);
      while (from !== -1 && ranges.length < MAX_HIGHLIGHT_RANGES) {
        const range = document.createRange();
        range.setStart(node, from);
        range.setEnd(node, from + needle.length);
        ranges.push(range);
        from = lowered.indexOf(needle, from + needle.length);
      }
    }
  }
  return ranges;
}

/**
 * Mark each rendered section that matched with `data-search-section` (the outlined, tinted section look in
 * `search-highlight.css`). The first matched id is the jump target and gets the value "jump", which also plays the
 * one-time flash. An attribute that is already present is left alone so a re-apply never restarts that flash, and
 * a section without a rendered element (the live turn, or one that is not mounted) is skipped.
 */
export function applySearchSectionMarks(
  container: HTMLElement,
  matchedIds: readonly string[],
  ownerAttribute: string,
): void {
  const matched = new Set(matchedIds);
  const jumpId = matchedIds[0];
  container.querySelectorAll<HTMLElement>(`[${ownerAttribute}]`).forEach(owner => {
    const id = owner.getAttribute(ownerAttribute) ?? '';
    if (!matched.has(id)) {
      owner.removeAttribute(SEARCH_SECTION_ATTRIBUTE);
    } else if (!owner.hasAttribute(SEARCH_SECTION_ATTRIBUTE)) {
      owner.setAttribute(SEARCH_SECTION_ATTRIBUTE, id === jumpId ? 'jump' : '');
    }
  });
}

export function clearSearchSectionMarks(container: HTMLElement): void {
  container.querySelectorAll<HTMLElement>(`[${SEARCH_SECTION_ATTRIBUTE}]`).forEach(owner => {
    owner.removeAttribute(SEARCH_SECTION_ATTRIBUTE);
  });
}

/**
 * Paint the searched words inside the matched sections using the CSS Custom Highlight API, which marks text without
 * touching the DOM, and mark the matched section elements. Only sections that are currently open have their text
 * rendered, so the marks are re-applied when `expandedKey` changes or the content re-renders. Browsers without the API
 * simply get no word marks; the section marks, the jump and the flash still work.
 */
export function useSearchHighlight(
  scrollRef: RefObject<HTMLElement | null>,
  focus: SearchFocus | null,
  owners: SearchHighlightOwners,
  expandedKey: string,
): void {
  const { ownerAttribute, fallbackOwnerId } = owners;
  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !focus) return undefined;
    const registry = highlightRegistry();
    const HighlightCtor = (globalThis as unknown as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
    const resolvedOwners: SearchHighlightOwners = { ownerAttribute, fallbackOwnerId };

    const apply = () => {
      applySearchSectionMarks(container, focus.matchedIds, ownerAttribute);
      if (!registry || !HighlightCtor) return;
      const ranges = collectMatchRanges(container, focus.tokens, focus.matchedIds, resolvedOwners);
      if (ranges.length === 0) registry.delete(SEARCH_HIGHLIGHT_NAME);
      else registry.set(SEARCH_HIGHLIGHT_NAME, new HighlightCtor(...ranges));
    };
    apply();

    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer = new MutationObserver(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(apply, REAPPLY_DELAY_MS);
    });
    observer.observe(container, { childList: true, subtree: true, characterData: true });

    return () => {
      if (timer) clearTimeout(timer);
      observer.disconnect();
      registry?.delete(SEARCH_HIGHLIGHT_NAME);
      clearSearchSectionMarks(container);
    };
  }, [scrollRef, focus, ownerAttribute, fallbackOwnerId, expandedKey]);
}
