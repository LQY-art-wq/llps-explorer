import assert from 'node:assert/strict';
import test from 'node:test';
import { withAnalysisSessionLock } from '../src/lib/session-bootstrap.ts';

test('anonymous session bootstrap is serialized across concurrent tabs', async () => {
  let tail = Promise.resolve();
  let active = 0;
  let maximumActive = 0;
  const lockManager = {
    request<T>(_name: string, options: { mode: 'exclusive' }, callback: () => Promise<T>): Promise<T> {
      assert.equal(options.mode, 'exclusive');
      const result = tail.then(async () => {
        active += 1; maximumActive = Math.max(maximumActive, active);
        try { return await callback(); } finally { active -= 1; }
      });
      tail = result.then(() => undefined, () => undefined);
      return result;
    },
  };
  const order: string[] = [];
  await Promise.all([
    withAnalysisSessionLock(async () => { order.push('first-start'); await Promise.resolve(); order.push('first-end'); }, lockManager),
    withAnalysisSessionLock(async () => { order.push('second-start'); order.push('second-end'); }, lockManager),
  ]);
  assert.equal(maximumActive, 1);
  assert.deepEqual(order, ['first-start', 'first-end', 'second-start', 'second-end']);
});

test('session bootstrap still runs where Web Locks are unavailable', async () => {
  assert.equal(await withAnalysisSessionLock(async () => 'ready', null), 'ready');
});
