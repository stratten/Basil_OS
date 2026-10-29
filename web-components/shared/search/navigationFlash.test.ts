// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { flashNavigationTarget } from './navigationFlash';

describe('flashNavigationTarget', () => {
  it('marks the element until its animation ends', () => {
    const element = document.createElement('div');
    flashNavigationTarget(element);
    expect(element.hasAttribute('data-navigation-flash')).toBe(true);
    element.dispatchEvent(new Event('animationend'));
    expect(element.hasAttribute('data-navigation-flash')).toBe(false);
  });

  it('ignores animation events that bubble up from a child', () => {
    const element = document.createElement('div');
    const child = document.createElement('span');
    element.appendChild(child);
    flashNavigationTarget(element);
    child.dispatchEvent(new Event('animationend', { bubbles: true }));
    expect(element.hasAttribute('data-navigation-flash')).toBe(true);
  });
});
