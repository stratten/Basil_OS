export const BASIL_CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'self' file:",
  "style-src 'self' file: 'unsafe-inline'",
  "img-src 'self' file: data: blob:",
  "font-src 'self' file: data:",
  "media-src 'self' file: data: blob:",
  "connect-src 'self' file: data: blob: http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*",
  'frame-src basil-inline-preview: basil-preview-file: http://127.0.0.1:* http://localhost:*',
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

export interface BasilContentSecurityPolicyTag {
  tag: 'meta';
  attrs: {
    'http-equiv': 'Content-Security-Policy';
    content: string;
  };
  injectTo: 'head-prepend';
}

export interface BasilContentSecurityPolicyPlugin {
  name: 'basil-content-security-policy';
  apply: 'build';
  transformIndexHtml: () => BasilContentSecurityPolicyTag[];
}

export function basilContentSecurityPolicy(): BasilContentSecurityPolicyPlugin {
  return {
    name: 'basil-content-security-policy',
    apply: 'build',
    transformIndexHtml: () => [
      {
        tag: 'meta',
        attrs: {
          'http-equiv': 'Content-Security-Policy',
          content: BASIL_CONTENT_SECURITY_POLICY,
        },
        injectTo: 'head-prepend',
      },
    ],
  };
}
