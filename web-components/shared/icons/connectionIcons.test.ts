import { describe, expect, it } from 'vitest';
import { bundledConnectionIcon, connectionIconSources, knownConnectionForUrl } from './connectionIcons';

describe('knownConnectionForUrl', () => {
  it.each([
    ['https://api.githubcopilot.com/mcp/', 'github'],
    ['https://mcp.linear.app/mcp', 'linear'],
    ['https://gmailmcp.googleapis.com/mcp/v1', 'gmail'],
    ['https://mcp.slack.com/mcp', 'slack'],
    ['basil-local://slack', 'slack'],
    ['HTTPS://MCP.LINEAR.APP/mcp', 'linear'],
  ])('recognizes %s as %s', (url, expected) => {
    expect(knownConnectionForUrl(url)).toBe(expected);
  });

  it.each([
    ['https://mcp.example.com/mcp'],
    ['https://slack.com.evil.example/mcp'],
    ['https://notgithub.com/mcp'],
    ['basil-local://other'],
    ['not a url'],
    [''],
    [null],
    [undefined],
  ])('does not recognize %s', (url) => {
    expect(knownConnectionForUrl(url as string | null | undefined)).toBeNull();
  });
});

describe('bundled connection icons', () => {
  it('has an SVG data URL for every known connection and none for others', () => {
    for (const url of ['https://api.githubcopilot.com/mcp/', 'https://mcp.linear.app/mcp', 'https://gmailmcp.googleapis.com/mcp/v1', 'basil-local://slack']) {
      expect(bundledConnectionIcon(url)).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
    }
    expect(bundledConnectionIcon('https://mcp.example.com/mcp')).toBeNull();
  });

  it('gives each known connection its own icon', () => {
    const icons = ['https://api.githubcopilot.com/mcp/', 'https://mcp.linear.app/mcp', 'https://gmailmcp.googleapis.com/mcp/v1', 'basil-local://slack'].map(bundledConnectionIcon);
    expect(new Set(icons).size).toBe(4);
  });
});

describe('connectionIconSources', () => {
  const advertised = 'data:image/png;base64,AAAA';

  it('puts the server-advertised icon first and the bundled one behind it', () => {
    const sources = connectionIconSources('https://mcp.linear.app/mcp', advertised);
    expect(sources).toHaveLength(2);
    expect(sources[0]).toBe(advertised);
    expect(sources[1]).toBe(bundledConnectionIcon('https://mcp.linear.app/mcp'));
  });

  it('falls back to the bundled icon when the server advertises none', () => {
    expect(connectionIconSources('https://mcp.linear.app/mcp', null)).toEqual([bundledConnectionIcon('https://mcp.linear.app/mcp')]);
    expect(connectionIconSources('https://mcp.linear.app/mcp')).toHaveLength(1);
  });

  it('uses only the advertised icon for an unknown server, and nothing when there is neither', () => {
    expect(connectionIconSources('https://mcp.example.com/mcp', advertised)).toEqual([advertised]);
    expect(connectionIconSources('https://mcp.example.com/mcp', null)).toEqual([]);
  });

  it('ignores an advertised value that is not an image data URL', () => {
    expect(connectionIconSources('https://mcp.example.com/mcp', 'https://tracker.example.com/pixel.png')).toEqual([]);
    expect(connectionIconSources('https://mcp.example.com/mcp', 'javascript:alert(1)')).toEqual([]);
  });
});
