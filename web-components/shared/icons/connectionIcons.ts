/** Icons for connections (remote MCP servers): a bundled set for the connections Basil knows, and the chain of sources a chip tries. */

// Marks are the Simple Icons paths (CC0) for Gmail, GitHub and Linear, each in its brand color, drawn without a background; the chip seats them on a light tile. Slack is a plain hash mark in Slack's aubergine, because Simple Icons no longer carries Slack's own logo. Drop the official asset in here to replace it.
const MARKS = {
  github: {
    fill: '#181717',
    path: 'M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12',
  },
  linear: {
    fill: '#5E6AD2',
    path: 'M2.886 4.18A11.982 11.982 0 0 1 11.99 0C18.624 0 24 5.376 24 12.009c0 3.64-1.62 6.903-4.18 9.105L2.887 4.18ZM1.817 5.626l16.556 16.556c-.524.33-1.075.62-1.65.866L.951 7.277c.247-.575.537-1.126.866-1.65ZM.322 9.163l14.515 14.515c-.71.172-1.443.282-2.195.322L0 11.358a12 12 0 0 1 .322-2.195Zm-.17 4.862 9.823 9.824a12.02 12.02 0 0 1-9.824-9.824Z',
  },
  gmail: {
    fill: '#EA4335',
    path: 'M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z',
  },
} as const;

function svgDataUrl(markup: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
}

function brandMark(mark: { fill: string; path: string }): string {
  return svgDataUrl(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="${mark.fill}" d="${mark.path}"/></svg>`);
}

const SLACK_HASH_MARK = svgDataUrl('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9.5 4.5 8 19.5M16 4.5 14.5 19.5M4.5 9.5h15M4 14.5h15" fill="none" stroke="#4A154B" stroke-width="2.4" stroke-linecap="round"/></svg>');

export type KnownConnection = 'github' | 'linear' | 'slack' | 'gmail';

const BUNDLED_ICONS: Record<KnownConnection, string> = {
  github: brandMark(MARKS.github),
  linear: brandMark(MARKS.linear),
  slack: SLACK_HASH_MARK,
  gmail: brandMark(MARKS.gmail),
};

// How each known connection is recognized from its server URL. The URL is what identifies a connection, because the person can rename it ("Gmail - Work") and the name then says nothing. Slack is served by Basil itself under a basil-local address until Slack's hosted server is approved, so both addresses count.
const KNOWN_HOSTS: ReadonlyArray<{ id: KnownConnection; hosts: readonly string[] }> = [
  { id: 'github', hosts: ['api.githubcopilot.com', 'github.com'] },
  { id: 'linear', hosts: ['mcp.linear.app', 'linear.app'] },
  { id: 'gmail', hosts: ['gmailmcp.googleapis.com'] },
  { id: 'slack', hosts: ['mcp.slack.com', 'slack.com'] },
];

const LOCAL_SLACK_PREFIX = 'basil-local://slack';

/** Which known connection a server URL belongs to, or null for any other server. */
export function knownConnectionForUrl(serverUrl: string | null | undefined): KnownConnection | null {
  const raw = (serverUrl ?? '').trim().toLowerCase();
  if (!raw) return null;
  if (raw.startsWith(LOCAL_SLACK_PREFIX)) return 'slack';
  let hostname: string;
  try {
    hostname = new URL(raw).hostname;
  } catch {
    return null;
  }
  for (const entry of KNOWN_HOSTS) {
    if (entry.hosts.some(host => hostname === host || hostname.endsWith(`.${host}`))) return entry.id;
  }
  return null;
}

/** The bundled icon for a known connection, or null for any other server. */
export function bundledConnectionIcon(serverUrl: string | null | undefined): string | null {
  const known = knownConnectionForUrl(serverUrl);
  return known ? BUNDLED_ICONS[known] : null;
}

/** The image sources a connection chip tries in order: the icon the server advertises first, then the bundled one. The chip skips any source that fails to load and ends on a plug glyph when none is left. */
export function connectionIconSources(serverUrl: string | null | undefined, advertisedIconDataUrl?: string | null): string[] {
  const sources: string[] = [];
  if (advertisedIconDataUrl && advertisedIconDataUrl.startsWith('data:image/')) sources.push(advertisedIconDataUrl);
  const bundled = bundledConnectionIcon(serverUrl);
  if (bundled) sources.push(bundled);
  return sources;
}
