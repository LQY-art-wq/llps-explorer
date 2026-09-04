export const ANALYSIS_SESSION_COOKIE = 'llps_analysis_session';
export const MAX_ANALYSIS_RETENTION_DAYS = 3650;
export const ANALYSIS_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * MAX_ANALYSIS_RETENTION_DAYS;

const ANALYSIS_SESSION_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export interface AnalysisSessionCookieOptions {
  httpOnly: true;
  sameSite: 'lax';
  secure: boolean;
  path: '/';
  maxAge: number;
}

export interface AnalysisSessionCookieTarget {
  cookies: {
    set(
      name: string,
      value: string,
      options: AnalysisSessionCookieOptions,
    ): unknown;
  };
}

export function resolveAnalysisSessionToken(
  existing: string | undefined,
  create: () => string,
): string {
  return existing && ANALYSIS_SESSION_PATTERN.test(existing) ? existing : create();
}

/** Refresh the same credential on every proxy response so it outlives any retained job. */
export function refreshAnalysisSessionCookie<T extends AnalysisSessionCookieTarget>(
  response: T,
  token: string,
  secure: boolean,
): T {
  response.cookies.set(ANALYSIS_SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure,
    path: '/',
    maxAge: ANALYSIS_SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
