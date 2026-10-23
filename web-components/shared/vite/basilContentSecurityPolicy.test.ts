import { describe, expect, it } from 'vitest';
import { BASIL_CONTENT_SECURITY_POLICY, basilContentSecurityPolicy } from './basilContentSecurityPolicy';

function directives(): Map<string, string[]> {
  return new Map(
    BASIL_CONTENT_SECURITY_POLICY.split(';').map((directive) => {
      const [name, ...sources] = directive.trim().split(/\s+/);
      return [name, sources] as [string, string[]];
    }),
  );
}

describe('basilContentSecurityPolicy', () => {
  it('applies only to production builds and prepends one CSP meta tag', () => {
    const plugin = basilContentSecurityPolicy();

    expect(plugin.name).toBe('basil-content-security-policy');
    expect(plugin.apply).toBe('build');
    expect(plugin.transformIndexHtml()).toEqual([
      {
        tag: 'meta',
        attrs: { 'http-equiv': 'Content-Security-Policy', content: BASIL_CONTENT_SECURITY_POLICY },
        injectTo: 'head-prepend',
      },
    ]);
  });

  it('denies by default and never allows inline or evaluated script', () => {
    const policy = directives();

    expect(policy.get('default-src')).toEqual(["'none'"]);
    expect(policy.get('script-src')).toEqual(["'self'", 'file:']);
    expect(BASIL_CONTENT_SECURITY_POLICY).not.toContain("'unsafe-eval'");
    expect(policy.get('script-src')).not.toContain("'unsafe-inline'");
    expect(policy.get('object-src')).toEqual(["'none'"]);
    expect(policy.get('base-uri')).toEqual(["'none'"]);
    expect(policy.get('form-action')).toEqual(["'none'"]);
  });

  it('limits network access to the loopback backend and local preview sources', () => {
    const policy = directives();

    expect(policy.get('connect-src')).toEqual([
      "'self'", 'file:', 'data:', 'blob:',
      'http://127.0.0.1:*', 'http://localhost:*', 'ws://127.0.0.1:*', 'ws://localhost:*',
    ]);
    expect(policy.get('frame-src')).toEqual([
      'basil-inline-preview:', 'basil-preview-file:', 'http://127.0.0.1:*', 'http://localhost:*',
    ]);
    expect(policy.get('img-src')).toEqual(["'self'", 'file:', 'data:', 'blob:']);
    expect(BASIL_CONTENT_SECURITY_POLICY).not.toContain('https:');
    expect(Array.from(policy.values()).flat()).not.toContain('*');
  });
});
