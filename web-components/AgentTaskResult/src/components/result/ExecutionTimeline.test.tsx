import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProgressStepsSection } from './ExecutionTimeline';
import type { TimelineEntry } from '../../types';

const timelineEntry = (id: string, overrides: Partial<TimelineEntry> = {}): TimelineEntry => ({
  id,
  type: 'step',
  timestamp: '2026-07-13T12:00:00Z',
  content: id,
  ...overrides,
});

describe('ProgressStepsSection live beacon', () => {
  it('renders the beacon for active execution', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        steps={[{ step: 'Running tool', isActive: true, isComplete: false }]}
        isProcessing
      />,
    );

    expect(markup).toContain('execution-live-beacon');
  });

  it('omits the beacon for historical execution', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        steps={[{ step: 'Completed tool', isActive: false, isComplete: true }]}
        isProcessing={false}
      />,
    );

    expect(markup).not.toContain('execution-live-beacon');
  });
});

describe('ProgressStepsSection activity trail', () => {
  it('renders a collapsed single-line header with the readable count and latest activity while processing', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        steps={[]}
        timeline={[
          timelineEntry('a', { content: 'Reading inbox', metadata: { progress_step: 'Reading inbox' } }),
          timelineEntry('b', { content: 'Drafting reply', metadata: { progress_step: 'Drafting reply' } }),
        ]}
        isProcessing
      />,
    );

    expect(markup).toContain('activity-summary');
    expect(markup).toContain('execution-live-beacon');
    expect(markup).toContain('Activity · 2 updates');
    expect(markup).toContain('Drafting reply');
    expect(markup).not.toContain('Reading inbox');
    expect(markup).toContain('aria-expanded="false"');
  });

  it('hides the trail when there is no timeline', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection steps={[]} timeline={[]} isProcessing={false} />,
    );

    expect(markup).not.toContain('activity-summary');
  });

  it('keeps the expandable list and Full Details collapsed behind the single-line header by default', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        steps={[]}
        timeline={[
          timelineEntry('a', { content: 'Reading inbox', metadata: { progress_step: 'Reading inbox' } }),
        ]}
        isProcessing={false}
      />,
    );

    expect(markup).toContain('Activity · 1 update');
    expect(markup).not.toContain('activity-summary-list');
    expect(markup).not.toContain('Full Details');
  });

  it('omits raw_detail tool entries from the collapsed readable count and latest activity', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        steps={[]}
        timeline={[
          timelineEntry('raw', {
            type: 'tool_complete',
            detail_kind: 'tool_result',
            content: 'Ran shell: verbose output',
            metadata: { raw_detail: true, progress_step: 'Ran shell: verbose output' },
          }),
          timelineEntry('progress', { content: 'Reading inbox', metadata: { progress_step: 'Reading inbox' } }),
        ]}
        isProcessing
      />,
    );

    expect(markup).toContain('Activity · 1 update');
    expect(markup).toContain('Reading inbox');
    expect(markup).not.toContain('Ran shell');
  });
});

describe('ProgressStepsSection dock presentation', () => {
  it('renders a collapsed dock header with readable count and latest activity', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        presentation="dock"
        steps={[]}
        timeline={[
          timelineEntry('a', { content: 'Reading inbox', metadata: { progress_step: 'Reading inbox' } }),
          timelineEntry('b', { content: 'Drafting reply', metadata: { progress_step: 'Drafting reply' } }),
        ]}
        isProcessing
      />,
    );

    expect(markup).toContain('execution-activity-dock');
    expect(markup).toContain('Activity · 2 updates');
    expect(markup).toContain('Drafting reply');
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).not.toContain('activity-summary');
    expect(markup).not.toContain('execution-steps-body');
    expect(markup).not.toContain('execution-activity-dock-body is-open');
  });

  it('does not render a dock for thinking-only timelines', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        presentation="dock"
        steps={[]}
        timeline={[
          timelineEntry('thinking', { type: 'thinking', content: 'Planning next move' }),
        ]}
        isProcessing
      />,
    );

    expect(markup).not.toContain('execution-activity-dock');
  });

  it('counts raw-detail entries only in Full Details, not the collapsed readable count', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        presentation="dock"
        steps={[]}
        timeline={[
          timelineEntry('raw', {
            type: 'tool_complete',
            content: 'Ran shell: verbose output',
            metadata: { raw_detail: true, progress_step: 'Ran shell: verbose output' },
          }),
          timelineEntry('progress', { content: 'Reading inbox', metadata: { progress_step: 'Reading inbox' } }),
        ]}
        isProcessing
      />,
    );

    expect(markup).toContain('Activity · 1 update');
    expect(markup).toContain('Reading inbox');
    expect(markup).not.toContain('Ran shell');
  });

  it('keeps completed activity collapsed in dock presentation', () => {
    const markup = renderToStaticMarkup(
      <ProgressStepsSection
        presentation="dock"
        steps={[]}
        timeline={[
          timelineEntry('completed', { content: 'Finished analysis', metadata: { progress_step: 'Finished analysis' } }),
        ]}
        isProcessing={false}
      />,
    );

    expect(markup).toContain('execution-activity-dock');
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).not.toContain('execution-activity-dock-body is-open');
  });
});
