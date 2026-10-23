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
