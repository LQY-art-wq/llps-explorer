import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ANALYSIS_SESSION_COOKIE,
  ANALYSIS_SESSION_MAX_AGE_SECONDS,
  MAX_ANALYSIS_RETENTION_DAYS,
  refreshAnalysisSessionCookie,
  resolveAnalysisSessionToken,
} from '../src/lib/analysis-session-cookie.ts';

const EXISTING_TOKEN = 'a'.repeat(43);

test('a valid existing anonymous session is reused and refreshed for maximum retention', () => {
  const token = resolveAnalysisSessionToken(EXISTING_TOKEN, () => {
    throw new Error('a valid existing session must not be replaced');
  });
  let written: { name: string; value: string; options: unknown } | null = null;
  const response = {
    cookies: {
      set(name: string, value: string, options: unknown) {
        written = { name, value, options };
      },
    },
  };

  assert.equal(refreshAnalysisSessionCookie(response, token, true), response);
  assert.deepEqual(written, {
    name: ANALYSIS_SESSION_COOKIE,
    value: EXISTING_TOKEN,
    options: {
      httpOnly: true,
      sameSite: 'lax',
      secure: true,
      path: '/',
      maxAge: 60 * 60 * 24 * 3650,
    },
  });
  assert.equal(MAX_ANALYSIS_RETENTION_DAYS, 3650);
  assert.equal(ANALYSIS_SESSION_MAX_AGE_SECONDS, 60 * 60 * 24 * MAX_ANALYSIS_RETENTION_DAYS);
});

test('an invalid or missing session is replaced without weakening local HTTP support', () => {
  let created = 0;
  const create = () => { created += 1; return 'b'.repeat(43); };
  assert.equal(resolveAnalysisSessionToken(undefined, create), 'b'.repeat(43));
  assert.equal(resolveAnalysisSessionToken('invalid', create), 'b'.repeat(43));
  assert.equal(created, 2);

  let secure: boolean | undefined;
  refreshAnalysisSessionCookie({ cookies: { set: (_name, _value, options) => {
    secure = options.secure;
  } } }, 'b'.repeat(43), false);
  assert.equal(secure, false);
});
