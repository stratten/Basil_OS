// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { checkFilePreviewAvailability } from './bridge';
import { captureScreenshot } from '../components/localWebPreview/localWebPreviewBridge';

describe('bridge behavior without a native host', () => {
  afterEach(() => {
    window.webkit = undefined;
  });

  it('assumes every unique path is available when the agent task handler is absent', async () => {
    window.webkit = undefined;
    await expect(checkFilePreviewAvailability(['/a.md', '/a.md', '/b.md'])).resolves.toEqual(new Set(['/a.md', '/b.md']));
  });

  it('assumes every path is available when webkit exists without the agent task handler', async () => {
    window.webkit = { messageHandlers: {} };
    await expect(checkFilePreviewAvailability(['/a.md'])).resolves.toEqual(new Set(['/a.md']));
  });

  it('resolves an empty path set without contacting the host', async () => {
    window.webkit = undefined;
    await expect(checkFilePreviewAvailability([])).resolves.toEqual(new Set());
  });

  it('resolves an empty screenshot payload when the local web preview handler is absent', async () => {
    window.webkit = undefined;
    await expect(captureScreenshot()).resolves.toEqual({});
  });
});
