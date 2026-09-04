import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ApiError, deleteAnalysis, getAnalysis, getAnalysisExport, getMethods, getPublicConfig,
  importFuzDrop, listAnalysisHistory, submitAnalysis,
} from '../src/lib/api.ts';
import type { AnalysisJob } from '../src/lib/contracts.ts';

const baseJob = { job_id: 'analysis_test', status: 'success', selected_methods: ['seg'], sequence: { name: null, length: 3, sha256: 'a'.repeat(64) }, methods: {}, ensemble: null, result_schema_version: '1.0' };
test('API calls stay same-origin and preserve all successful DTO values for download', async (context) => {
  const original = { ...baseJob, methods: { seg: { method: 'seg', status: 'success', result: { coverage: 0, regions: [] } } }, audit_marker: 'preserved' };
  const calls: { url: string; options?: RequestInit }[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options?: RequestInit) => {
    calls.push({ url, options }); return Response.json(original, { status: 202 });
  });
  const controller = new AbortController();
  const request = { sequence: 'ACD', selected_methods: ['seg'] as ['seg'], prediction_mode: 'independent' as const };
  const result = await submitAnalysis(request, controller.signal);
  assert.deepEqual(result, original);
  assert.equal(calls[0].url, '/api/v1/analysis'); assert.equal(calls[0].options?.signal, controller.signal);
  assert.deepEqual(JSON.parse(calls[0].options?.body as string), request);
  assert.equal(calls[0].options?.cache, 'no-store');
  assert.equal(calls[0].options?.credentials, 'same-origin');
  await getAnalysis('analysis_test', controller.signal);
  assert.equal(calls[1].url, '/api/v1/analysis/analysis_test'); assert.equal(calls[1].options?.method, 'GET');
  assert.equal(calls[1].options?.body, undefined);
});
test('history requests bounded filters and validates the lightweight summary envelope', async (context) => {
  const item = { job_id: 'analysis_test', sequence_name: 'protein', sequence_length: 3,
    created_at: '2026-09-04T00:00:00Z', updated_at: '2026-09-04T00:01:00Z', completed_at: null,
    expires_at: '2026-09-11T00:00:00Z', status: 'interrupted', selected_methods: ['seg'],
    prediction_mode: 'independent', lreca_score: null, fuzdrop_score: null, ensemble_score: null,
    result_schema_version: '1.0' };
  let requestUrl = '';
  context.mock.method(globalThis, 'fetch', async (url: string) => {
    requestUrl = url; return Response.json({ items: [item], total: 1, limit: 25, offset: 50 });
  });
  assert.deepEqual(await listAnalysisHistory({ limit: 25, offset: 50, status: 'interrupted', method: 'seg' }),
    { items: [item], total: 1, limit: 25, offset: 50 });
  assert.equal(requestUrl, '/api/v1/analysis/history?limit=25&offset=50&status=interrupted&method=seg');
});
test('history and detail reject unsupported persisted result schema versions', async (context) => {
  const badHistory = { job_id: 'analysis_test', sequence_name: null, sequence_length: 3,
    created_at: '2026-09-04T00:00:00Z', updated_at: '2026-09-04T00:01:00Z', completed_at: null,
    expires_at: '2026-09-11T00:00:00Z', status: 'success', selected_methods: ['seg'],
    prediction_mode: 'independent', lreca_score: null, fuzdrop_score: null, ensemble_score: null,
    result_schema_version: '2.0' };
  context.mock.method(globalThis, 'fetch', async () => Response.json({ items: [badHistory], total: 1, limit: 20, offset: 0 }));
  await assert.rejects(listAnalysisHistory(), { code: 'INVALID_RESPONSE' });
  context.mock.restoreAll();
  context.mock.method(globalThis, 'fetch', async () => Response.json({ ...baseJob, result_schema_version: '2.0' }));
  await assert.rejects(getAnalysis('analysis_test'), { code: 'INVALID_RESPONSE' });
});
test('public config exposes only the validated retention duration', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ analysis_retention_days: 7 }));
  assert.deepEqual(await getPublicConfig(), { analysis_retention_days: 7 });
  context.mock.restoreAll();
  context.mock.method(globalThis, 'fetch', async () => Response.json({ analysis_retention_days: 0, database_url: 'private' }));
  await assert.rejects(getPublicConfig(), { code: 'INVALID_RESPONSE' });
});
test('delete uses the owned same-origin endpoint and requires the backend 204 contract', async (context) => {
  const calls: { url: string; options: RequestInit }[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, options }); return new Response(null, { status: 204 });
  });
  await deleteAnalysis('analysis_test');
  assert.equal(calls[0]?.url, '/api/v1/analysis/analysis_test');
  assert.equal(calls[0]?.options.method, 'DELETE');
  assert.equal(calls[0]?.options.credentials, 'same-origin');
});
test('downloads use backend export bytes, attachment filename, MIME type, and original precision', async (context) => {
  const csv = 'Position,AA,LRECA_Attribution\r\n1,A,0.123456789012345\r\n';
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/v1/analysis/analysis_test/export/residues.csv');
    assert.equal(new Headers(options.headers).get('accept'), 'text/csv');
    return new Response(csv, { headers: { 'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="protein_analysis_test_residues.csv"' } });
  });
  const result = await getAnalysisExport('analysis_test', 'residues.csv');
  assert.equal(result.filename, 'protein_analysis_test_residues.csv');
  assert.equal(result.contentType, 'text/csv; charset=utf-8');
  assert.equal(await result.blob.text(), csv);
});
test('download refuses an unexpected successful content type', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response('<html>private</html>', { headers: { 'Content-Type': 'text/html' } }));
  await assert.rejects(getAnalysisExport('analysis_test', 'json'), { code: 'INVALID_RESPONSE' });
});
test('active analysis download keeps the backend not-ready status and actionable guidance', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({
    detail: { code: 'ANALYSIS_NOT_READY_FOR_EXPORT', message: 'private upstream text' },
  }, { status: 409 }));
  await assert.rejects(getAnalysisExport('analysis_test', 'json'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'ANALYSIS_NOT_READY_FOR_EXPORT');
    assert.equal(error.status, 409);
    assert.match(error.message, /still running/);
    assert.doesNotMatch(error.message, /private upstream text/);
    return true;
  });
});
test('method catalog unwraps the real methods envelope', async (context) => {
  const rows = [{ id: 'fuzdrop', automatic_analysis_available: false, manual_import_available: true }];
  context.mock.method(globalThis, 'fetch', async () => Response.json({ methods: rows }));
  assert.deepEqual(await getMethods(), rows);
});
test('FuzDrop sends only the official import contract and retains result ID and null science fields', async (context) => {
  const payload = { sequence: 'ACD', source_declaration: 'official_fuzdrop_export' as const, coordinate_system: 'one_based_inclusive' as const, scores_tsv: 'test fixture text', pLLPS: null };
  const value = { method: 'fuzdrop', status: 'success', validation_status: 'valid', result_id: 'fuzdrop_result_test', sequence: 'ACD', sequence_sha256: 'a'.repeat(64), expires_at: '2026-10-01T00:00:00Z', raw_score: null };
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/v1/methods/fuzdrop/import'); assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body as string), payload); return Response.json(value);
  });
  assert.deepEqual(await importFuzDrop(payload), value);
});
for (const status of ['partial_success', 'failed', 'external_result_required'] as const) {
  test(`${status} is a normal job response, including unavailable ensemble`, async (context) => {
    const value = { ...baseJob, status, ensemble: { status: 'unavailable', score: null, label: null, reason: 'fuzdrop_global_score_missing' } };
    context.mock.method(globalThis, 'fetch', async () => Response.json(value));
    assert.deepEqual(await getAnalysis('analysis_test'), value);
  });
}
for (const [code, status] of [['FUZDROP_SEQUENCE_MISMATCH', 422], ['ANALYSIS_UNAVAILABLE', 503], ['ANALYSIS_JOB_NOT_FOUND', 404], ['FUZDROP_IMPORT_TOO_LARGE', 413]] as const) {
  test(`safe structured ${code} errors never echo body, internal paths, or traceback`, async (context) => {
    const privateText = `${process.cwd()}/private-server/traceback ACDEFGHIKLMNPQRSTVWY`;
    context.mock.method(globalThis, 'fetch', async () => Response.json({ detail: { code, message: privateText, input: privateText } }, { status }));
    await assert.rejects(getAnalysis('analysis_test'), (error: unknown) => {
      assert.ok(error instanceof ApiError); assert.equal(error.code, code); assert.equal(error.status, status);
      assert.equal(error.message.includes(privateText), false); assert.equal(error.message.includes('traceback'), false); return true;
    });
  });
}
test('unknown errors and malformed JSON use fixed fallback messages', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ detail: { code: 'PRIVATE_UNKNOWN', message: 'private' } }, { status: 500 }));
  await assert.rejects(getMethods(), (error: unknown) => error instanceof ApiError && error.code === 'REQUEST_FAILED' && !error.message.includes('private'));
  context.mock.restoreAll();
  context.mock.method(globalThis, 'fetch', async () => new Response('<html>private failure</html>', { status: 200 }));
  await assert.rejects(getMethods(), (error: unknown) => error instanceof ApiError && error.code === 'INVALID_RESPONSE');
});
for (const [code, status, guidance] of [
  ['REQUEST_TOO_LARGE', 413, '5 MiB'],
  ['INVALID_CONTENT_TYPE', 415, 'JSON'],
  ['INVALID_REQUEST_ORIGIN', 403, 'same workspace'],
  ['API_ROUTE_NOT_FOUND', 404, 'not available'],
] as const) {
  test(`proxy ${code} keeps its code and actionable guidance without exposing server details`, async (context) => {
    const privateText = `${process.cwd()}/private-server/traceback ACDEFGHIKLMNPQRSTVWY`;
    context.mock.method(globalThis, 'fetch', async () => Response.json({
      detail: { code, message: privateText, input: privateText, context: { secret: privateText } },
    }, { status }));
    await assert.rejects(getMethods(), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, code); assert.equal(error.status, status);
      assert.ok(error.message.includes(guidance));
      assert.equal(error.message.includes(privateText), false);
      assert.equal(error.message.includes('traceback'), false);
      assert.equal(error.message.includes('ACDEFGHIKLMNPQRSTVWY'), false);
      return true;
    });
  });
}
test('network failure becomes a friendly safe error; abort retains cancellation semantics', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => { throw new Error('private stack'); });
  await assert.rejects(getMethods(), (error: unknown) => error instanceof ApiError && error.code === 'NETWORK_ERROR');
  const controller = new AbortController(); controller.abort();
  await assert.rejects(getMethods(controller.signal), { name: 'AbortError' });
});
test('abort while reading the response body remains cancellation rather than a visible service error', async (context) => {
  const controller = new AbortController();
  context.mock.method(globalThis, 'fetch', async () => {
    const response = Response.json({});
    context.mock.method(response, 'json', async () => { controller.abort(); throw new DOMException('Stopped', 'AbortError'); });
    return response;
  });
  await assert.rejects(getMethods(controller.signal), { name: 'AbortError' });
});
test('invalid IDs cannot be used to construct a different request path', async (context) => {
  let called = false;
  context.mock.method(globalThis, 'fetch', async () => { called = true; return Response.json(baseJob); });
  await assert.rejects(getAnalysis('../methods'), { code: 'ANALYSIS_JOB_NOT_FOUND' }); assert.equal(called, false);
});
test('a response for another job cannot replace the requested job', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ ...baseJob, job_id: 'different' }));
  await assert.rejects(getAnalysis('analysis_test'), { code: 'INVALID_RESPONSE' });
});
test('unknown job statuses and malformed catalog are rejected', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ ...baseJob, status: 'fabricated' }));
  await assert.rejects(getAnalysis('analysis_test'), { code: 'INVALID_RESPONSE' });
  context.mock.restoreAll();
  context.mock.method(globalThis, 'fetch', async () => Response.json({ methods: 'not an array' }));
  await assert.rejects(getMethods(), { code: 'INVALID_RESPONSE' });
});
// Type-level result fixture explicitly has no frontend-calculated ensemble score.
void (baseJob as unknown as AnalysisJob);
