import test from 'node:test';
import assert from 'node:assert/strict';
import type { FuzDropImportResponse, MethodDescriptor } from '../src/lib/contracts.ts';
import { availableAutomaticMethods, complementaryWeights, evaluateDraft, ImportSession, importedStateForSequence, isTerminalJob, snapshotInput, validateImportedResponse } from '../src/lib/analysis-state.ts';
import type { DraftSelection } from '../src/lib/analysis-state.ts';
import { sequenceSha256 } from '../src/lib/sequence.ts';

const methods = ['lreca', 'seg', 'fuzdrop', 'dismeta'].map((id) => ({ id, available: id !== 'dismeta', method_supported: true,
  automatic_analysis_available: id === 'lreca' || id === 'seg', manual_import_available: id === 'fuzdrop',
  integration_mode: id === 'fuzdrop' ? 'manual_import' : id === 'dismeta' ? 'integration_blocked' : 'local_automatic',
})) as MethodDescriptor[];
const hash = await sequenceSha256('ACD');
function imported(updates: Partial<FuzDropImportResponse> = {}): FuzDropImportResponse {
  return { method: 'fuzdrop', method_id: 'fuzdrop', status: 'success', validation_status: 'valid', result_id: 'fuzdrop_result_test',
    sequence: 'ACD', sequence_length: 3, sequence_sha256: hash, raw_score: 0.7, calibrated_score: 0.7,
    expires_at: new Date(Date.now() + 60_000).toISOString(), ...updates } as FuzDropImportResponse;
}
function draft(updates: Partial<DraftSelection> = {}): DraftSelection {
  return { rawSequence: 'acd', sequenceName: 'test', methods, selectedAutomatic: ['lreca', 'seg'], imported: null,
    useFuzDrop: false, mode: 'independent', lrecaPercent: 50, ...updates };
}
test('default automatic selection excludes manual and blocked methods even if descriptor is misflagged', () => {
  assert.deepEqual(availableAutomaticMethods(methods), ['lreca', 'seg']);
  assert.deepEqual(availableAutomaticMethods(methods.map((row) => ({ ...row, automatic_analysis_available: true, integration_mode: 'local_automatic' }))), ['lreca', 'seg']);
  assert.deepEqual(availableAutomaticMethods(methods.map((row) => ({ ...row, available: false }))), []);
});
for (const selectedAutomatic of [[], ['lreca'], ['seg'], ['lreca', 'seg']] as const) {
  test(`independent payload supports ${selectedAutomatic.join('+') || 'no methods disabled'}`, () => {
    const result = evaluateDraft(draft({ selectedAutomatic: [...selectedAutomatic] }));
    if (!selectedAutomatic.length) { assert.equal(result.request, null); return; }
    assert.deepEqual(result.request, { sequence: 'ACD', sequence_name: 'test', selected_methods: [...selectedAutomatic], prediction_mode: 'independent', weights: null, external_results: {} });
  });
}
test('import success requires an explicit toggle before FuzDrop is selected', () => {
  const disabled = evaluateDraft(draft({ imported: imported() }));
  assert.deepEqual(disabled.request?.selected_methods, ['lreca', 'seg']);
  const enabled = evaluateDraft(draft({ selectedAutomatic: [], imported: imported(), useFuzDrop: true }));
  assert.deepEqual(enabled.request?.selected_methods, ['fuzdrop']);
  assert.deepEqual(enabled.request?.external_results, { fuzdrop: { result_id: 'fuzdrop_result_test' } });
});
test('SEG-only remains an annotation request without prediction weights or FuzDrop', () => {
  const result = evaluateDraft(draft({ selectedAutomatic: ['seg'], imported: imported(), lrecaPercent: Number.NaN }));
  assert.deepEqual(result.request?.selected_methods, ['seg']); assert.equal(result.request?.weights, null);
});
test('unavailable selected automatic methods are removed from the request', () => {
  const result = evaluateDraft(draft({ methods: methods.map((row) => row.id === 'lreca' ? { ...row, automatic_analysis_available: false } : row) }));
  assert.deepEqual(result.request?.selected_methods, ['seg']);
});
for (const updates of [
  { imported: null }, { imported: imported(), useFuzDrop: false }, { selectedAutomatic: ['seg'] },
  { imported: imported({ raw_score: null, calibrated_score: null }) },
  { imported: imported({ sequence: 'ACE' }) }, { imported: imported({ expires_at: '2000-01-01T00:00:00Z' }) },
] satisfies Partial<DraftSelection>[]) test(`weighted mode is blocked without both usable global predictors ${JSON.stringify(updates)}`, () => {
  const current = draft({ imported: imported(), useFuzDrop: true, mode: 'weighted', ...updates });
  assert.equal(evaluateDraft(current).request, null); assert.ok(evaluateDraft(current).weightedDisabledReason);
  assert.equal(current.mode, 'weighted');
});
test('weighted payload forwards exact complementary weights and never calculates a score', () => {
  const result = evaluateDraft(draft({ imported: imported(), useFuzDrop: true, mode: 'weighted', lrecaPercent: 60 }));
  assert.deepEqual(result.request?.weights, { lreca: 0.6, fuzdrop: 0.4 });
  assert.equal(Object.hasOwn(result.request ?? {}, 'score'), false);
  assert.equal(result.weightedDisabledReason, null);
});
test('zero global score is present, not missing', () => {
  assert.ok(evaluateDraft(draft({ imported: imported({ raw_score: 0, calibrated_score: 0 }), useFuzDrop: true, mode: 'weighted' })).request);
});
test('a malformed import without a global numeric score cannot enable weighted mode', () => {
  const missing = imported(); delete (missing as Partial<FuzDropImportResponse>).raw_score;
  assert.equal(evaluateDraft(draft({ imported: missing, useFuzDrop: true, mode: 'weighted' })).request, null);
});
test('weights preserve endpoints and decimals; invalid values cannot run', () => {
  for (const percent of [0, 33.3, 50, 60, 100]) {
    const values = complementaryWeights(percent)!;
    assert.ok(Math.abs(values.lreca + values.fuzdrop - 1) <= 1e-9);
  }
  for (const percent of [-1, 101, Infinity, NaN]) {
    assert.equal(complementaryWeights(percent), null);
    assert.equal(evaluateDraft(draft({ imported: imported(), useFuzDrop: true, mode: 'weighted', lrecaPercent: percent })).request, null);
  }
});
test('invalid sequence or name cannot be submitted', () => {
  assert.equal(evaluateDraft(draft({ rawSequence: 'ACX' })).request, null);
  assert.equal(evaluateDraft(draft({ sequenceName: 'x'.repeat(129) })).request, null);
});
test('import identity independently verifies the canonical sequence SHA and length', async () => {
  assert.equal(await validateImportedResponse(imported(), 'ACD'), 'valid');
  assert.equal(await validateImportedResponse(imported({ sequence_sha256: '0'.repeat(64) }), 'ACD'), 'sequence_mismatch');
  assert.equal(await validateImportedResponse(imported({ sequence_length: 2 }), 'ACD'), 'sequence_mismatch');
  assert.equal(importedStateForSequence(imported({ expires_at: 'bad-date' }), 'ACD'), 'invalid');
});
test('editing away and back permanently invalidates an accepted import', async () => {
  const session = new ImportSession(); assert.equal(await session.accept(imported(), 'ACD', 0), true);
  session.invalidate(); session.invalidate();
  assert.equal(session.imported, null); assert.equal(session.status, 'sequence_mismatch');
  assert.equal(await session.accept(imported(), 'ACD', 0), false);
});
test('an import arriving after sequence editing is rejected, even during hash validation', async () => {
  const session = new ImportSession(); const pending = session.accept(imported(), 'ACD', 0);
  session.invalidate(); assert.equal(await pending, false); assert.equal(session.imported, null);
});
test('late import responses cannot replace the newest accepted import', async () => {
  const session = new ImportSession();
  const older = session.accept(imported({ result_id: 'old' }), 'ACD', 0);
  const newer = session.accept(imported({ result_id: 'new' }), 'ACD', 0);
  assert.equal(await older, false); assert.equal(await newer, true); assert.equal(session.imported?.result_id, 'new');
});
test('remove cancels pending import validation; expiry clears its binding', async () => {
  const session = new ImportSession(); const pending = session.accept(imported(), 'ACD', 0);
  session.remove(); assert.equal(await pending, false); assert.equal(session.status, 'not_imported');
  const value = imported(); await session.accept(value, 'ACD', 0);
  assert.equal(session.expire(Date.parse(value.expires_at)), true); assert.equal(session.imported, null); assert.equal(session.status, 'expired');
});
test('input snapshots retain the exact submitted sequence while a new job is in flight', () => {
  const input = snapshotInput({ rawSequence: '>name\nacd', sequenceName: 'manual name' }, '2026-01-01T00:00:00Z');
  assert.equal(input.canonical, 'ACD'); assert.equal(input.inputType, 'fasta'); assert.equal(input.sequenceName, 'manual name');
  assert.equal(input.rawSequence, '>name\nacd'); assert.equal(input.submittedAt, '2026-01-01T00:00:00Z');
});
for (const status of ['success', 'partial_success', 'failed', 'interrupted', 'unavailable', 'external_result_required'] as const) {
  test(`${status} is terminal and keeps its distinct status`, () => { assert.equal(isTerminalJob({ status }), true); });
}
