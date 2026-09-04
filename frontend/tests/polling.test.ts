import test from 'node:test';
import assert from 'node:assert/strict';
import type { AnalysisJob } from '../src/lib/contracts.ts';
import { abortableDelay, ApiError, pollAnalysis } from '../src/lib/api.ts';

const job = (status: AnalysisJob['status'], job_id = 'analysis_test') => ({ job_id, status } as AnalysisJob);
test('polling waits one second between sequential GETs and stops at success', async () => {
  const calls: string[] = []; const delays: number[] = []; const received: string[] = [];
  let active = 0; let maxActive = 0;
  const statuses: AnalysisJob['status'][] = ['running', 'running', 'success'];
  const result = await pollAnalysis({ jobId: 'analysis_test', signal: new AbortController().signal,
    onJob: (value) => received.push(value.status), wait: async (milliseconds) => { delays.push(milliseconds); },
    fetchJob: async (id) => { active++; maxActive = Math.max(active, maxActive); calls.push(id); await Promise.resolve(); active--; return job(statuses.shift()!); } });
  assert.equal(result.status, 'success'); assert.equal(maxActive, 1);
  assert.deepEqual(delays, [1000, 1000, 1000]); assert.equal(calls.length, 3);
  assert.deepEqual(received, ['running', 'running', 'success']);
});
for (const status of ['partial_success', 'failed', 'unavailable', 'external_result_required'] as const) {
  test(`poll stops normally at ${status}`, async () => {
    let calls = 0;
    const result = await pollAnalysis({ jobId: 'analysis_test', signal: new AbortController().signal, immediate: true,
      fetchJob: async () => { calls++; return job(status); }, onJob: () => {}, wait: async () => { throw new Error('No further polling'); } });
    assert.equal(result.status, status); assert.equal(calls, 1);
  });
}
test('an initial terminal response needs no extra GET', async () => {
  let called = false;
  await pollAnalysis({ jobId: 'analysis_test', initialJob: job('success'), signal: new AbortController().signal,
    onJob: () => {}, fetchJob: async () => { called = true; return job('success'); } });
  assert.equal(called, false);
});
test('poll failure stops and an explicit retry performs only GET on the same job', async () => {
  const ids: string[] = [];
  const signal = new AbortController().signal;
  await assert.rejects(pollAnalysis({ jobId: 'analysis_test', signal, immediate: true, onJob: () => {},
    fetchJob: async (id) => { ids.push(id); throw new ApiError('NETWORK_ERROR'); } }), { code: 'NETWORK_ERROR' });
  const retried = await pollAnalysis({ jobId: 'analysis_test', signal, immediate: true, onJob: () => {},
    fetchJob: async (id) => { ids.push(id); return job('success'); } });
  assert.equal(retried.status, 'success'); assert.deepEqual(ids, ['analysis_test', 'analysis_test']);
});
test('abort while waiting releases the timer without a GET', async () => {
  const controller = new AbortController(); let calls = 0;
  const pending = pollAnalysis({ jobId: 'analysis_test', signal: controller.signal, onJob: () => {},
    fetchJob: async () => { calls++; return job('success'); } });
  controller.abort(); await assert.rejects(pending, { name: 'AbortError' }); assert.equal(calls, 0);
});
test('abort during an in-flight request discards a late result', async () => {
  const controller = new AbortController(); let receive!: (value: AnalysisJob) => void; let updates = 0;
  const pending = pollAnalysis({ jobId: 'analysis_test', signal: controller.signal, immediate: true,
    onJob: () => { updates++; }, fetchJob: () => new Promise((resolve) => { receive = resolve; }) });
  controller.abort(); receive(job('success'));
  await assert.rejects(pending, { name: 'AbortError' }); assert.equal(updates, 0);
});
test('old job polling and new job polling remain isolated', async () => {
  const first = new AbortController(); let finish!: (value: AnalysisJob) => void; const seen: string[] = [];
  const old = pollAnalysis({ jobId: 'old', signal: first.signal, immediate: true, onJob: (value) => seen.push(value.job_id),
    fetchJob: () => new Promise((resolve) => { finish = resolve; }) });
  first.abort();
  await pollAnalysis({ jobId: 'new', signal: new AbortController().signal, immediate: true,
    onJob: (value) => seen.push(value.job_id), fetchJob: async () => job('success', 'new') });
  finish(job('success', 'old')); await assert.rejects(old, { name: 'AbortError' }); assert.deepEqual(seen, ['new']);
});
test('delay rejects an already-aborted signal immediately', async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(abortableDelay(1000, controller.signal), { name: 'AbortError' });
});
