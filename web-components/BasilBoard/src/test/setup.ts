import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  document.queryCommandState = vi.fn().mockReturnValue(false) as typeof document.queryCommandState;
  document.execCommand = vi.fn().mockReturnValue(true) as typeof document.execCommand;
  Object.defineProperty(HTMLElement.prototype, 'innerText', {
    configurable: true,
    get() {
      return this.textContent ?? '';
    },
  });
});
