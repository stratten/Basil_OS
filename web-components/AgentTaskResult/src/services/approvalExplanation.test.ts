import { describe, expect, it } from 'vitest';
import { approvalExplanationFromContext } from './approvalExplanation';

describe('approvalExplanationFromContext', () => {
  it('reads every explanation field from an approval context', () => {
    expect(
      approvalExplanationFromContext({
        cwd: '/tmp',
        purpose: 'Builds the report.',
        whitelist: { eligible: false, reason: 'python can run any code.', advice: { recommend: false, reason: 'Script.', downgraded: true } },
        script_path: '/tmp/report.py',
        script_notice: 'Too large.',
      }),
    ).toEqual({
      purpose: 'Builds the report.',
      whitelist: { eligible: false, reason: 'python can run any code.', advice: { recommend: false, reason: 'Script.', downgraded: true } },
      script_path: '/tmp/report.py',
      script_notice: 'Too large.',
    });
  });

  it('reads the pattern that remembering would store and whether it is broad', () => {
    expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: null, pattern: 'gh gist view', broad: false } }))
      .toEqual({ whitelist: { eligible: true, reason: '', advice: null, pattern: 'gh gist view' } });
    expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: null, pattern: 'ls', broad: true } }))
      .toEqual({ whitelist: { eligible: true, reason: '', advice: null, pattern: 'ls', broad: true } });
    expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: null, pattern: '  ', broad: 'yes' } }))
      .toEqual({ whitelist: { eligible: true, reason: '', advice: null } });
  });

  it('reads the one connected tool that remembering would always allow', () => {
    const scope = { connection_id: 'conn-gmail', connection_name: 'Gmail', tool_name: 'trash_message', destructive: true };

    expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: null, pattern: '', broad: false, tool_policy: scope } }))
      .toEqual({ whitelist: { eligible: true, reason: '', advice: null, tool_policy: scope } });
    expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: null, tool_policy: { ...scope, destructive: 'yes', connection_name: 7 } } }))
      .toEqual({ whitelist: { eligible: true, reason: '', advice: null, tool_policy: { ...scope, connection_name: '', destructive: false } } });
  });

  it('drops a connected-tool scope that names no connection or no tool', () => {
    for (const broken of [null, 'x', {}, { connection_id: 'c' }, { tool_name: 't' }, { connection_id: ' ', tool_name: 't' }]) {
      expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: null, tool_policy: broken } }))
        .toEqual({ whitelist: { eligible: true, reason: '', advice: null } });
    }
  });

  it('keeps who wrote the explanation only when Basil did and a purpose arrived', () => {
    expect(approvalExplanationFromContext({ purpose: 'Connect Example.', purpose_source: 'basil' })).toEqual({ purpose: 'Connect Example.', purpose_source: 'basil' });
    expect(approvalExplanationFromContext({ purpose: 'Lists it.', purpose_source: 'agent' })).toEqual({ purpose: 'Lists it.' });
    expect(approvalExplanationFromContext({ purpose: 'Lists it.', purpose_source: 'system' })).toEqual({ purpose: 'Lists it.' });
    expect(approvalExplanationFromContext({ purpose: '   ', purpose_source: 'basil' })).toEqual({});
    expect(approvalExplanationFromContext({ purpose_source: 'basil', purpose_missing: true })).toEqual({ purpose_missing: true });
  });

  it('marks an unexplained command only when no purpose arrived', () => {
    expect(approvalExplanationFromContext({ purpose_missing: true })).toEqual({ purpose_missing: true });
    expect(approvalExplanationFromContext({ purpose_missing: true, purpose: 'Does it.' })).toEqual({ purpose: 'Does it.' });
  });

  it('drops malformed advice and ignores missing or non-object contexts', () => {
    expect(approvalExplanationFromContext({ whitelist: { eligible: true, reason: '', advice: { recommend: 'yes', reason: 'x' } } }))
      .toEqual({ whitelist: { eligible: true, reason: '', advice: null } });
    expect(approvalExplanationFromContext({ whitelist: { reason: 'x' }, purpose: '   ' })).toEqual({});
    expect(approvalExplanationFromContext(undefined)).toEqual({});
    expect(approvalExplanationFromContext('text')).toEqual({});
    expect(approvalExplanationFromContext(['a'])).toEqual({});
  });
});
