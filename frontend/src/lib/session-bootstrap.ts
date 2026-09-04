interface ExclusiveLockManager {
  request<T>(name: string, options: { mode: 'exclusive' }, callback: () => Promise<T>): Promise<T>;
}

/** Serializes the first owner-scoped request across same-origin browser tabs. */
export async function withAnalysisSessionLock<T>(
  task: () => Promise<T>,
  lockManager: ExclusiveLockManager | null = typeof navigator === 'undefined' ? null : navigator.locks,
): Promise<T> {
  if (!lockManager) return task();
  return lockManager.request('llps-analysis-session-bootstrap', { mode: 'exclusive' }, task);
}
