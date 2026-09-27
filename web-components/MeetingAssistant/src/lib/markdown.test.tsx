import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MeetingMarkdown } from './markdown';

describe('MeetingMarkdown', () => {
  it('removes executable link protocols while retaining safe links', () => {
    render(<MeetingMarkdown content={'[unsafe](javascript:alert(1)) [safe](https://example.com)'} />);
    expect(screen.getByText('unsafe')).not.toHaveAttribute('href');
    expect(screen.getByText('safe')).toHaveAttribute('href', 'https://example.com');
  });
});
