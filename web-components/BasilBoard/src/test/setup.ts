import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

// The 1000ms default times out under heavy CPU contention, such as all web suites running concurrently.
configure({ asyncUtilTimeout: 3000 });

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
