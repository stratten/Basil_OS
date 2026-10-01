import { describe, expect, it } from 'vitest';
import {
  isUserFacingResponseStreaming,
  normalizeResultForPresentation,
  runDetailsHint,
  splitRunDetails,
} from './resultContentUtils';

describe('user-facing response streaming', () => {
  it('begins only with a streaming visible result', () => {
    expect(isUserFacingResponseStreaming(true, 'First visible token')).toBe(true);
    expect(isUserFacingResponseStreaming(true, '')).toBe(false);
    expect(isUserFacingResponseStreaming(false, 'Completed response')).toBe(false);
  });
});

describe('legacy result presentation', () => {
  it('removes only the obsolete completed-with-warnings prefix', () => {
    expect(normalizeResultForPresentation(
      'Completed with warnings: The requested work was delivered.',
      'completed_with_warnings',
    )).toBe('The requested work was delivered.');
    expect(normalizeResultForPresentation(
      'Partial result: Some requested work remains.',
      'partial',
    )).toBe('Partial result: Some requested work remains.');
  });
});

describe('run details split', () => {
  const narrative = 'Here is the summary of your inbox.';
  const finalizerBlock = '• Active app at request: Mail\n\n• File: report.md\n\n• Path: /Users/me/report.md\n\n• Tool calls: 4';

  it('separates the finalizer metadata block from the narrative', () => {
    const result = splitRunDetails(`${narrative}\n\n${finalizerBlock}\n\n`);

    expect(result.narrative).toBe(narrative);
    expect(result.details).toEqual([
      { key: 'app', label: 'Active app', value: 'Mail' },
      { key: 'file', label: 'File', value: 'report.md' },
      { key: 'path', label: 'Path', value: '/Users/me/report.md' },
      { key: 'toolCalls', label: 'Tool calls', value: '4' },
    ]);
    expect(runDetailsHint(result.details)).toBe('4 tool calls · Mail');
  });

  it('shows a stored legacy "Steps: N/N completed" line as the tool-call total', () => {
    const result = splitRunDetails(`${narrative}\n\n• Active app at request: Mail\n\n• Steps: 12/14 completed`);

    expect(result.narrative).toBe(narrative);
    expect(result.details).toEqual([
      { key: 'app', label: 'Active app', value: 'Mail' },
      { key: 'toolCalls', label: 'Tool calls', value: '14' },
    ]);
    expect(runDetailsHint(result.details)).toBe('14 tool calls · Mail');
  });

  it('uses the singular for one tool call', () => {
    expect(runDetailsHint(splitRunDetails(`${narrative}\n\n• Tool calls: 1`).details)).toBe('1 tool call');
  });

  it('leaves model-authored trailing bullets in the narrative', () => {
    const text = `${narrative}\n\n• File: notes.md\n\n• Steps: review the draft`;
    const toolCallsProse = `${narrative}\n\n• Tool calls: several, see above`;

    expect(splitRunDetails(text)).toEqual({ narrative: text, details: [] });
    expect(splitRunDetails(toolCallsProse)).toEqual({ narrative: toolCallsProse, details: [] });
  });

  it('keeps a metadata-only summary visible as the narrative', () => {
    expect(splitRunDetails('• Tool calls: 2')).toEqual({ narrative: '• Tool calls: 2', details: [] });
    expect(splitRunDetails('• Steps: 2/2 completed')).toEqual({ narrative: '• Steps: 2/2 completed', details: [] });
  });

  it('returns ordinary and empty text unchanged', () => {
    expect(splitRunDetails('Plain answer.')).toEqual({ narrative: 'Plain answer.', details: [] });
    expect(splitRunDetails('')).toEqual({ narrative: '', details: [] });
  });

  it('keeps special characters in values', () => {
    const app = 'Visual Studio Code — "Basil" (Beta): main.ts';
    const result = splitRunDetails(`${narrative}\n\n• Active app at request: ${app}`);

    expect(result.narrative).toBe(narrative);
    expect(result.details).toEqual([{ key: 'app', label: 'Active app', value: app }]);
    expect(runDetailsHint(result.details)).toBe(app);
  });
});
