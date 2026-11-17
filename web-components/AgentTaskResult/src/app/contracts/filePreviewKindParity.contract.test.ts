import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// The side panel reviews whatever the backend snapshots for a task, while the pop-out preview window classifies files with the native Swift table. If the two drift, a file reads fine in the panel and shows "not supported" in the window.
const BACKEND_CAPTURE = '../../backend/src/api/services/agent_processing/lifecycle/runtime/artifact_revision_capture.py';
const NATIVE_RESOLVER = '../../client/Sources/App/AgentTaskCapture/FilePreview/FilePreviewKindResolver.swift';

function backendReviewableExtensions(): string[] {
  const source = readFileSync(BACKEND_CAPTURE, 'utf8');
  const block = source.slice(source.indexOf('_EXTENSION_KIND'));
  const table = block.slice(0, block.indexOf('\n}'));
  return [...table.matchAll(/"\.(\w+)":\s*"\w+"/g)].map(match => match[1]);
}

function nativeKindsByExtension(): Map<string, string> {
  const source = readFileSync(NATIVE_RESOLVER, 'utf8');
  const start = source.indexOf('static func kind(forExtension');
  const body = source.slice(start, source.indexOf('static func mimeType', start));
  const kinds = new Map<string, string>();
  for (const match of body.matchAll(/case\s+((?:"[^"]+"\s*,?\s*)+):\s*(?:\/\/[^\n]*\n\s*)?return\s+"(\w+)"/g)) {
    for (const extension of match[1].matchAll(/"([^"]+)"/g)) kinds.set(extension[1], match[2]);
  }
  return kinds;
}

describe('file preview kind parity', () => {
  it('reads both tables', () => {
    expect(backendReviewableExtensions().length).toBeGreaterThan(10);
    expect(nativeKindsByExtension().size).toBeGreaterThan(10);
  });

  it('previews every extension the backend snapshots for task review', () => {
    const native = nativeKindsByExtension();
    const unsupported = backendReviewableExtensions().filter(extension => !native.has(extension) || native.get(extension) === 'unsupported');
    expect(unsupported).toEqual([]);
  });
});
