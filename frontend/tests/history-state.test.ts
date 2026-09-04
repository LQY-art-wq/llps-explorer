import assert from 'node:assert/strict';
import test from 'node:test';
import type { AnalysisHistoryItem, AnalysisJob } from '../src/lib/contracts.ts';
import {
  historyPredictionSummary, lastHistoryOffset, normalizeHistoryQuery, persistedInput, safeDownloadFilename,
} from '../src/lib/history-state.ts';

const job = {
  job_id: 'analysis_test', created_at: '2026-09-04T00:00:00Z', updated_at: '2026-09-04T00:01:00Z',
  expires_at: '2026-09-11T00:00:00Z', status: 'success', normalized_sequence: 'ACD',
  sequence: { name: 'protein', length: 3, sha256: '00e66854ddc46722ac3db985136265f4a24bcbbf0b45103d80cfea510e9217bf' }, selected_methods: ['seg'],
  prediction_mode: 'independent', weights: null, methods: {}, ensemble: null, warnings: [],
  result_schema_version: '1.0',
} as AnalysisJob;

test('persisted job detail restores an immutable viewer input without running a method', async () => {
  assert.deepEqual(await persistedInput(job), {
    rawSequence: 'ACD', canonical: 'ACD', sequenceName: 'protein', length: 3,
    validResidues: 3, inputType: 'persisted', submittedAt: '2026-09-04T00:00:00Z',
  });
  assert.equal(await persistedInput({ ...job, normalized_sequence: undefined }), null);
  assert.equal(await persistedInput({ ...job, normalized_sequence: 'ACX' }), null);
  assert.equal(await persistedInput({ ...job, normalized_sequence: 'AC', sequence: { ...job.sequence, length: 3 } }), null);
  assert.equal(await persistedInput({ ...job, sequence: { ...job.sequence, sha256: 'a'.repeat(64) } }), null);
});

test('history queries are bounded and only accept real status and method filters', () => {
  assert.deepEqual(normalizeHistoryQuery({ limit: 500, offset: -2, status: 'interrupted', method: 'seg' }),
    { limit: 100, offset: 0, status: 'interrupted', method: 'seg' });
  assert.deepEqual(normalizeHistoryQuery({ limit: 0, status: 'made_up' as 'success', method: 'fake' as 'seg' }),
    { limit: 1, offset: 0, status: '', method: '' });
});

test('history pagination returns to the last populated page after deletion', () => {
  assert.equal(lastHistoryOffset(21, 20), 20);
  assert.equal(lastHistoryOffset(20, 20), 0);
  assert.equal(lastHistoryOffset(0, 20), 0);
});

test('history prediction summary treats zero as an actual persisted score', () => {
  const item = { lreca_score: 0, fuzdrop_score: null, ensemble_score: 0.125 } as AnalysisHistoryItem;
  assert.equal(historyPredictionSummary(item), 'LRECA 0.000 · Combined 0.125');
  assert.equal(historyPredictionSummary({ ...item, lreca_score: null, ensemble_score: null }), 'No global score');
});

test('download filenames accept safe Unicode and reject path or control injection', () => {
  assert.equal(safeDownloadFilename('attachment; filename="protein_job.json"', 'fallback.json'), 'protein_job.json');
  assert.equal(safeDownloadFilename("attachment; filename*=UTF-8''%E8%9B%8B%E7%99%BD_job.fasta", 'fallback.fasta'), '蛋白_job.fasta');
  assert.equal(safeDownloadFilename('attachment; filename="../secret.csv"', 'fallback.csv'), 'fallback.csv');
  assert.equal(safeDownloadFilename('inline; filename="wrong.json"', 'fallback.json'), 'fallback.json');
  assert.equal(safeDownloadFilename('attachment; filename="bad\\name.csv"', 'fallback.csv'), 'fallback.csv');
});
