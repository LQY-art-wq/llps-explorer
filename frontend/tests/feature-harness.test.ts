/** Explicit synthetic render/format fixtures; these tests do not validate scientific predictions. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  createFeatureTestFixture, FEATURE_TEST_LENGTHS, FEATURE_TEST_NOTICE,
  featureViewerTestEnabled, summarizeFeaturePerformance,
} from '../src/lib/feature-test-fixtures.ts';
import { buildFeatureViewerModel, getFeatureTooltip } from '../src/lib/feature-viewer-model.ts';
import { nativeResults } from '../src/lib/viewer-data.ts';

test('the test route requires the exact explicit server flag', () => {
  for (const value of [undefined, '', '0', 'true', 'TRUE', ' 1', '1 ', 'false']) {
    assert.equal(featureViewerTestEnabled(value), false);
  }
  assert.equal(featureViewerTestEnabled('1'), true);
});

for (const length of FEATURE_TEST_LENGTHS) {
  test(`the ${length}-residue synthetic fixture maps to the six production tracks`, async () => {
    const fixture = await createFeatureTestFixture(length);
    assert.equal(fixture.kind, 'synthetic_render_fixture');
    assert.equal(fixture.notice, FEATURE_TEST_NOTICE);
    assert.match(fixture.notice, /No model inference/);
    assert.equal(fixture.input.canonical.length, length);
    assert.match(fixture.input.canonical, /^[ACDEFGHIKLMNPQRSTVWY]+$/);
    assert.equal(fixture.job.sequence.length, length);
    assert.equal(fixture.job.sequence.sha256,
      createHash('sha256').update(fixture.input.canonical).digest('hex'));
    assert.deepEqual(fixture.job.selected_methods, ['lreca', 'fuzdrop', 'seg']);
    assert.equal(fixture.job.methods.dismeta, undefined);
    assert.equal(fixture.job.ensemble, null);
    assert.equal(fixture.job.weights, null);
    for (const execution of Object.values(fixture.job.methods)) {
      assert.ok(execution?.warnings.some((warning) => warning.startsWith('SYNTHETIC_TEST_DATA:')));
    }

    const model = buildFeatureViewerModel(fixture.job, fixture.input);
    assert.equal(model.analysisId, fixture.job.job_id);
    assert.equal(model.coordinateSystem, 'one_based_inclusive');
    assert.equal(model.sequence, fixture.input.canonical);
    assert.deepEqual(model.issues, []);
    assert.deepEqual(model.tracks.map((track) => track.id), [
      'lreca-attribution', 'lreca-kde', 'lreca-critical',
      'fuzdrop-propensity', 'fuzdrop-regions', 'seg-regions',
    ]);
    assert.equal(model.outputStates.find((state) => state.method === 'dismeta')?.status, 'unavailable');
    for (const track of model.tracks) {
      if (track.kind === 'continuous') assert.equal(track.values.length, length);
      else for (const region of track.regions) {
        assert.ok(region.start >= 1 && region.end <= length && region.end >= region.start);
        assert.equal(region.length, region.end - region.start + 1);
      }
    }
    const native = nativeResults(fixture.job);
    assert.ok(native.lreca?.residue_attribution);
    native.lreca.residue_attribution.forEach((row, index) => {
      assert.equal(row.position, index + 1);
      assert.equal(row.aa, fixture.input.canonical[index]);
      assert.ok(Number.isFinite(row.score) && row.score >= 0 && row.score <= 1);
    });
    const kde = model.tracks.find((track) => track.id === 'lreca-kde');
    assert.ok(kde?.kind === 'continuous');
    assert.ok(kde.values.some((value) => value !== null && value > 1));
    assert.deepEqual(kde.values, native.lreca.kde?.values);
    assert.equal(kde.valueDomain, null);
  });
}

test('native missing pDP stays null and duplicate overlapping regions keep independent identities', async () => {
  const fixture = await createFeatureTestFixture(500);
  const native = nativeResults(fixture.job);
  assert.equal(native.fuzdrop?.source, 'manual_import_of_official_result');
  assert.equal(native.fuzdrop?.origin_verification, 'user_declared_not_independently_verified');
  assert.equal(native.fuzdrop?.residue_propensity?.[96].score, null);
  assert.ok(native.fuzdrop?.residue_propensity?.some((row) => row.Sbind !== null && row.Sbind > 1));
  const model = buildFeatureViewerModel(fixture.job, fixture.input);
  const propensity = model.tracks.find((track) => track.id === 'fuzdrop-propensity');
  assert.ok(propensity?.kind === 'continuous');
  assert.equal(propensity.values[96], null);
  const track = model.tracks.find((item) => item.id === 'fuzdrop-regions');
  assert.ok(track?.kind === 'region');
  assert.equal(track.regions.length, 5);
  assert.equal(new Set(track.regions.map((region) => region.id)).size, 5);
  assert.deepEqual(track.regions.map(({ start, end }) => ({ start, end })),
    native.fuzdrop?.regions?.map(({ start, end }) => ({ start, end })));
  assert.equal(track.regions[2].start, track.regions[4].start);
  assert.equal(track.regions[2].end, track.regions[4].end);
  assert.equal(getFeatureTooltip(model, 97)?.rows.find((row) => row.id === 'fuzdrop-propensity')?.text, 'N/A');
});

test('first, last, and single-residue boundaries are exercised with inclusive tooltips', async () => {
  const { job, input } = await createFeatureTestFixture(100);
  const model = buildFeatureViewerModel(job, input);
  const first = getFeatureTooltip(model, 1);
  const last = getFeatureTooltip(model, 100);
  assert.equal(first?.aa, input.canonical[0]);
  assert.equal(last?.aa, input.canonical[99]);
  assert.equal(first?.rows.find((row) => row.id === 'fuzdrop-regions')?.regions[0].length, 1);
  assert.equal(last?.rows.find((row) => row.id === 'fuzdrop-regions')?.regions[0].length, 1);
  assert.equal(getFeatureTooltip(model, 0), null);
  assert.equal(getFeatureTooltip(model, 101), null);
});

test('a new analysis changes identity and regenerated fixtures do not share mutable arrays', async () => {
  const original = await createFeatureTestFixture(100, 1);
  const next = await createFeatureTestFixture(100, 2);
  assert.notEqual(original.job.job_id, next.job.job_id);
  assert.equal(original.job.sequence.sha256, next.job.sequence.sha256);
  const originalNative = nativeResults(original.job);
  const nextNative = nativeResults(next.job);
  assert.deepEqual(originalNative, nextNative);
  assert.ok(originalNative.lreca?.residue_attribution);
  assert.ok(nextNative.lreca?.residue_attribution);
  originalNative.lreca.residue_attribution[0].score = 0;
  assert.notEqual(nextNative.lreca.residue_attribution[0].score, 0);
});

test('the malformed pDP scenario rejects only its residue track and retains the other five exactly', async () => {
  const normal = await createFeatureTestFixture(500);
  const malformed = await createFeatureTestFixture(500, 1, 'malformed_fuzdrop_residue');
  assert.equal(malformed.scenario, 'malformed_fuzdrop_residue');
  assert.notEqual(malformed.job.job_id, normal.job.job_id);
  const normalModel = buildFeatureViewerModel(normal.job, normal.input);
  const malformedModel = buildFeatureViewerModel(malformed.job, malformed.input);
  assert.deepEqual(malformedModel.tracks,
    normalModel.tracks.filter((track) => track.id !== 'fuzdrop-propensity'));
  assert.equal(malformedModel.tracks.length, 5);
  assert.deepEqual(malformedModel.issues.map(({ outputId, code }) => ({ outputId, code })),
    [{ outputId: 'fuzdrop-propensity', code: 'INVALID_TRACK' }]);
  assert.equal(malformedModel.outputStates.find((row) => row.id === 'fuzdrop-propensity')?.status, 'invalid');
  assert.deepEqual(malformedModel.outputStates.filter((row) => row.id !== 'fuzdrop-propensity'),
    normalModel.outputStates.filter((row) => row.id !== 'fuzdrop-propensity'));
  assert.equal(nativeResults(malformed.job).fuzdrop?.residue_propensity?.[250].position, 0);
  assert.equal(nativeResults(normal.job).fuzdrop?.residue_propensity?.[250].position, 251);
});

test('unsupported lengths and invalid fixture revisions fail without truncation', async () => {
  for (const length of [0, 99, 101, 500.5, 5001, NaN, Infinity]) {
    await assert.rejects(createFeatureTestFixture(length), RangeError);
  }
  for (const revision of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    await assert.rejects(createFeatureTestFixture(100, revision), RangeError);
  }
});

test('performance summaries report missing measurements as null rather than zero', () => {
  assert.deepEqual(summarizeFeaturePerformance([]), [
    { kind: 'initial_render', count: 0, medianMs: null, p95Ms: null, maxMs: null },
    { kind: 'zoom', count: 0, medianMs: null, p95Ms: null, maxMs: null },
    { kind: 'hover', count: 0, medianMs: null, p95Ms: null, maxMs: null },
  ]);
});

test('performance statistics use actual finite observations and nearest-rank p95 per event', () => {
  const samples = Array.from({ length: 20 }, (_, index) => ({ kind: 'zoom' as const, durationMs: index + 1 }));
  const summary = summarizeFeaturePerformance([
    ...samples, { kind: 'zoom', durationMs: NaN }, { kind: 'zoom', durationMs: -1 },
    { kind: 'zoom', durationMs: Infinity }, { kind: 'hover', durationMs: 0 },
  ]);
  assert.deepEqual(summary[1], { kind: 'zoom', count: 20, medianMs: 10.5, p95Ms: 19, maxMs: 20 });
  assert.deepEqual(summary[2], { kind: 'hover', count: 1, medianMs: 0, p95Ms: 0, maxMs: 0 });
  assert.equal(samples[0].durationMs, 1);
});

test('the explicitly synthetic global-only import material has no invented residue or region data', async () => {
  const directory = new URL('../../docs/audit/module7_browser/fixtures/', import.meta.url);
  const payload = JSON.parse(await readFile(new URL('synthetic_fuzdrop_global_only_248aa.json', directory), 'utf8'));
  const manifest = JSON.parse(await readFile(new URL('fixture_manifest.json', directory), 'utf8'));
  assert.deepEqual(Object.keys(payload).sort(), ['coordinate_system', 'pLLPS', 'sequence', 'source_declaration']);
  assert.equal(payload.sequence.length, 248);
  assert.equal(payload.pLLPS, 0.68);
  assert.equal(payload.coordinate_system, 'one_based_inclusive');
  assert.equal(payload.source_declaration, 'official_fuzdrop_export');
  assert.equal(manifest.scientific_prediction, false);
  assert.equal(manifest.official_origin_verified, false);
  assert.match(manifest.notice, /synthetic/i);
  assert.equal(createHash('sha256').update(payload.sequence).digest('hex'), manifest.sequence_sha256);
  for (const [filename, expectedHash] of Object.entries(manifest.file_sha256)) {
    const bytes = await readFile(new URL(filename, directory));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expectedHash);
  }
});
