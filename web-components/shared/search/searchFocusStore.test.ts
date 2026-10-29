// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { clearSearchFocus, getSearchFocus, publishSearchFocus } from './searchFocusStore';

afterEach(() => clearSearchFocus());

describe('searchFocusStore', () => {
  it('publishes a focus with a fresh nonce each time, even for the same scope', () => {
    publishSearchFocus({ scopeId: 'chat-1', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['m1'] });
    const first = getSearchFocus();
    publishSearchFocus({ scopeId: 'chat-1', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['m1'] });
    expect(getSearchFocus()?.nonce).toBeGreaterThan(first?.nonce ?? 0);
    expect(getSearchFocus()).toEqual(expect.objectContaining({ scopeId: 'chat-1', matchedIds: ['m1'] }));
  });

  it('clears the focus and ignores a second clear', () => {
    publishSearchFocus({ scopeId: 'chat-1', query: 'q', tokens: ['qq'], matchedIds: [] });
    clearSearchFocus();
    expect(getSearchFocus()).toBeNull();
    expect(() => clearSearchFocus()).not.toThrow();
  });
});
