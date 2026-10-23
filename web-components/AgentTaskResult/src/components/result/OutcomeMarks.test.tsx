// @vitest-environment node

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { StatusIcon } from '../sidebar/SidebarIcons';
import { TurnStatusGlyph } from './TurnLabel';

describe('partial outcome mark', () => {
  it('draws the turn glyph for a partial turn as the half-filled green mark, and other turns as before', () => {
    const partial = renderToStaticMarkup(<TurnStatusGlyph status="partial" tooltip="Partial result" />);
    expect(partial).toContain('outcome-partial-mark');
    expect(partial).toContain('turn-status-glyph--partial');
    expect(partial).not.toContain('<svg');
    expect(renderToStaticMarkup(<TurnStatusGlyph status="success" />)).toContain('<svg');
    expect(renderToStaticMarkup(<TurnStatusGlyph status="failed" />)).not.toContain('outcome-partial-mark');
  });

  it('draws the sidebar status icon for a warning-severity result as the same mark, sized to the icon', () => {
    const markup = renderToStaticMarkup(<StatusIcon status="completed" resultSeverity="warning" size={8} />);
    expect(markup).toContain('outcome-partial-mark');
    expect(markup).toContain('--outcome-mark-size:8px');
    expect(markup).not.toContain('var(--warning-base)');
  });

  it('keeps working in purple and never in amber or the literal orange', () => {
    const markup = renderToStaticMarkup(<StatusIcon status="processing" size={8} />);
    expect(markup).toContain('var(--processing-base)');
    expect(markup).not.toContain('orange');
  });
});
