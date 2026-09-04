/** Synthetic DTOs only. These exercise presentation contracts, not model inference. */
import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  AnalysisJob, FuzDropImportResponse, FuzDropResult, InputSnapshot, LRECAResult,
  MethodExecution, MethodId, SEGResult,
} from '../src/lib/contracts.ts';
import {
  buildViewerData, displayedFuzDrop, explainReason, formatCoverage, formatNumber, nativeResults,
  paginateRows, statusPresentation,
} from '../src/lib/viewer-data.ts';
import { combinedPredictionStatus } from '../src/components/result-status.ts';

const SEQUENCE = 'ACDEFGHIKLMNPQRSTVWY';
const snapshot: InputSnapshot = {
  rawSequence: `>Synthetic\n${SEQUENCE}`, canonical: SEQUENCE, sequenceName: 'Synthetic',
  length: SEQUENCE.length, validResidues: SEQUENCE.length, inputType: 'fasta',
  submittedAt: '2026-01-01T00:00:00Z',
};

function lreca(): LRECAResult {
  return {
    method_id: 'lreca', method: 'lreca', status: 'success', message: null,
    semantic_type: 'model_prediction', model_variant: 'human_specific',
    dataset5_mapping_status: 'unconfirmed', repository_commit: '0'.repeat(40),
    checkpoint: 'synthetic_fixture.pt', checkpoint_sha256: '0'.repeat(64),
    metadata: { repository: 'https://github.com/ai-phasepro/LRECA', commit: '0'.repeat(40),
      model_variant: 'human_specific', dataset5_mapping_status: 'unconfirmed',
      checkpoint: 'synthetic_fixture.pt', checkpoint_sha256: '0'.repeat(64), checkpoint_size_bytes: 1 },
    sequence: SEQUENCE, sequence_length: SEQUENCE.length, raw_score: 0.82,
    calibrated_score: 0.82, calibration_status: 'not_calibrated',
    score_semantics: 'uncalibrated_positive_class_softmax', positive_class_index: 1,
    threshold: 0.5, threshold_operator: '>', logits: [0, 1], label: 'P', device: 'cpu', runtime_ms: 1,
    attribution_status: 'success', attribution_reason: null,
    attribution_semantic_type: 'model_attribution',
    attribution_normalization: 'official_absolute_maximum_diverging_scale',
    attribution_target_class_index: 1, attribution_target_label: 'P',
    residue_attribution: Array.from(SEQUENCE, (aa, index) => ({ position: index + 1, aa,
      score: index === 0 ? 0.123456789 : 0, semantic_type: 'model_attribution' })),
    top_residues: [{ position: 1, aa: 'A', score: 0.123456789, rank: 1, semantic_type: 'model_attribution' }],
    kde: { status: 'success', semantic_type: 'derived_hotspot',
      values: Array.from(SEQUENCE, (_, index) => index + 0.987654321),
      values_semantics: 'Synthetic density values, not attribution or positions',
      prominence: 0.1, regions: [{ start: 1, end: 19, length: 19, score: 3.1459,
        is_primary: true, semantic_type: 'derived_hotspot' }],
      bandwidth: 0.2, reason: null, warnings: [], input_precision: 'official_csv_4_decimal_places', runtime_ms: 1 },
    critical_regions: [{ start: 1, end: 19, length: 19, score: 3.1459,
      is_primary: true, semantic_type: 'derived_hotspot' }],
    warnings: [], timings_ms: null,
  };
}

function fuzdrop(score: number | null = 0.68): FuzDropImportResponse {
  return {
    method_id: 'fuzdrop', method: 'fuzdrop', status: 'success', message: null,
    mode: 'C', integration_mode: 'browser_protected', semantic_type: 'model_prediction',
    sequence: SEQUENCE, sequence_length: SEQUENCE.length, raw_score: score,
    calibrated_score: score, calibration_status: 'not_calibrated', score_semantics: 'official_pLLPS',
    label: score === null ? null : score >= 0.6 ? 'P' : 'N', label_semantics: null,
    threshold: score === null ? null : 0.6, threshold_operator: score === null ? null : '>=',
    residue_propensity: Array.from(SEQUENCE, (aa, index) => ({ position: index + 1, aa,
      score: index === 0 ? null : 0.234567891, score_name: 'pDP', Sbind: 2.5,
      semantic_type: 'residue_propensity', Sbind_semantics: 'binding_mode_entropy' })),
    regions: [
      { type: 'droplet_promoting_region', official_type: 'Droplet-promoting region',
        start: 5, end: 5, length: 1, semantic_type: 'region_prediction' },
      { type: 'aggregation_hotspot', official_type: 'Aggregation hot-spot',
        start: 1, end: 2, length: 2, semantic_type: 'region_prediction' },
      { type: 'droplet_promoting_region', official_type: 'Droplet-promoting region',
        start: 5, end: 5, length: 1, semantic_type: 'region_prediction' },
    ],
    source: 'manual_import_of_official_result', source_declaration: 'official_fuzdrop_export',
    origin_verification: 'user_declared_not_independently_verified', coordinate_system: 'one_based_inclusive',
    coordinate_verification: 'user_declared_not_independently_verified',
    official_site_url: 'https://fuzdrop.bio.unipd.it/predictor', service_version: null,
    retrieved_at: null, imported_at: '2026-01-01T00:00:00Z', sequence_sha256: '0'.repeat(64),
    raw_tsv_sha256: { scores_tsv: '1'.repeat(64), regions_tsv: '2'.repeat(64) },
    raw_response_sha256: null, runtime_ms: 1, runtime_scope: 'local_import_parsing', warnings: [],
    result_id: 'fuzdrop_result_' + '0'.repeat(32), expires_at: '2026-01-01T01:00:00Z', validation_status: 'valid',
  };
}

function seg(empty = false): SEGResult {
  return {
    method_id: 'seg', method: 'seg', status: 'success', message: null,
    annotation_type: 'LCR', semantic_type: 'region_annotation', implementation: 'NCBI segmasker',
    version: '2.17.0', application_version: '1.0.0', executable_sha256: '0'.repeat(64),
    sequence_length: SEQUENCE.length, sequence_sha256: '0'.repeat(64),
    regions: empty ? [] : [{ start: 2, end: 5, length: 4, semantic_type: 'region_annotation' }],
    parameters: { window: 12, locut: 2.2, hicut: 2.5, input_format: 'fasta', output_format: 'interval', parse_seqids: false },
    runtime_ms: 1, coverage: empty ? 0 : 0.2, region_count: empty ? 0 : 1, longest_region: empty ? 0 : 4,
  };
}

function execution(result: LRECAResult | FuzDropResult | SEGResult): MethodExecution {
  return { method: result.method, status: 'success', result,
    integration_mode: result.method === 'fuzdrop' ? 'manual_import' : 'local_automatic',
    runtime_ms: 1, error: null, reason: null, warnings: [] };
}

function job(results: (LRECAResult | FuzDropResult | SEGResult)[] = []): AnalysisJob {
  const methods: Partial<Record<MethodId, MethodExecution>> = {};
  results.forEach((result) => { methods[result.method] = execution(result); });
  return { job_id: 'analysis_synthetic', created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:01Z', expires_at: '2026-01-01T01:00:01Z', status: 'success',
    sequence: { name: 'Synthetic', length: SEQUENCE.length, sha256: '0'.repeat(64) },
    selected_methods: results.map((result) => result.method), prediction_mode: 'independent',
    weights: null, methods, ensemble: null, warnings: [], result_schema_version: '1.0' };
}

test('no job yields an empty viewer, never a mock sequence or zero-score track', () => {
  const data = buildViewerData(null, snapshot);
  assert.equal(data.sequence, null);
  assert.equal(data.sequenceLength, null);
  assert.equal(data.lrecaAttribution, null);
  assert.equal(data.segRegions, null);
  assert.ok(data.tracks.every((track) => !track.available && track.count === null));
});

test('all track values, precision, coordinates and semantic types pass through unchanged', () => {
  const source = job([lreca(), fuzdrop(), seg()]);
  const before = JSON.stringify(source);
  const data = buildViewerData(source, snapshot);
  assert.equal(data.sequence, SEQUENCE);
  assert.equal(data.coordinateSystem, 'one_based_inclusive');
  assert.equal(data.lrecaAttribution?.[0].score, 0.123456789);
  assert.equal(data.lrecaKDE?.values?.[0], 0.987654321);
  assert.equal(data.lrecaCriticalRegions?.[0].end, 19);
  assert.equal(data.segRegions?.[0].start, 2);
  assert.equal(data.fuzdropResiduePropensity?.[0].score, null);
  assert.equal(data.fuzdropResiduePropensity?.[0].Sbind, 2.5);
  assert.deepEqual(data.fuzdropRegions?.map(({ start, end }) => [start, end]), [[5, 5], [1, 2], [5, 5]]);
  assert.deepEqual(data.tracks.map((track) => track.semanticType), [
    'model_attribution', 'derived_hotspot', 'derived_hotspot', 'residue_propensity', 'region_prediction', 'region_annotation',
  ]);
  assert.equal(JSON.stringify(source), before);
});

test('empty native regions remain available empty data, unlike a missing method', () => {
  const data = buildViewerData(job([seg(true)]), snapshot);
  assert.deepEqual(data.segRegions, []);
  assert.equal(data.tracks.find((track) => track.id === 'seg-regions')?.available, true);
  assert.equal(data.tracks.find((track) => track.id === 'seg-regions')?.count, 0);
  assert.equal(data.fuzdropRegions, null);
  assert.equal(data.tracks.find((track) => track.id === 'fuzdrop-regions')?.available, false);
});

test('unavailable KDE stays unavailable while real attribution is preserved', () => {
  const result = lreca();
  result.kde = { ...result.kde!, status: 'unavailable', values: null, regions: null, reason: 'short_sequence' };
  result.critical_regions = null;
  const data = buildViewerData(job([result]), snapshot);
  assert.equal(data.lrecaKDE?.reason, 'short_sequence');
  assert.equal(data.tracks.find((track) => track.id === 'lreca-kde')?.count, null);
  assert.equal(data.lrecaAttribution?.length, SEQUENCE.length);
});

test('failed execution cannot contribute stale native values', () => {
  const source = job([lreca()]);
  source.methods.lreca!.status = 'failed';
  assert.equal(nativeResults(source).lreca, null);
  assert.equal(buildViewerData(source, snapshot).lrecaAttribution, null);
});

test('a newer import never fills or replaces a historical job result', () => {
  assert.equal(displayedFuzDrop(job([lreca()]), fuzdrop(0.99)), null);
  assert.equal(displayedFuzDrop(job([fuzdrop(0.68)]), fuzdrop(0.99))?.raw_score, 0.68);
  assert.equal(displayedFuzDrop(null, fuzdrop(0.99))?.raw_score, 0.99);
});

test('a regions-only FuzDrop import does not acquire a global score', () => {
  const imported = fuzdrop(null);
  assert.equal(displayedFuzDrop(null, imported)?.raw_score, null);
  const data = buildViewerData(job([imported]), snapshot);
  assert.equal(data.fuzdropRegions?.length, 3);
  assert.equal(formatNumber(imported.raw_score), '—');
});

test('SEG-only viewer uses its paired submitted snapshot, not a current draft', () => {
  const source = job([seg()]);
  assert.equal(buildViewerData(source, snapshot).sequence, SEQUENCE);
  assert.equal(buildViewerData(source, { ...snapshot, length: 1, canonical: 'A' }).sequence, null);
  assert.equal(buildViewerData(source, null).sequence, null);
});

test('a native canonical sequence takes precedence over a stale snapshot', () => {
  assert.equal(buildViewerData(job([lreca()]), { ...snapshot, canonical: 'Q'.repeat(20) }).sequence, SEQUENCE);
});

test('zero and missing scores or coverage have distinct display values', () => {
  assert.equal(formatNumber(0), '0.000');
  assert.equal(formatNumber(null), '—');
  assert.equal(formatNumber(undefined), '—');
  assert.equal(formatNumber(Number.NaN), '—');
  assert.equal(formatCoverage(0), '0.00%');
  assert.equal(formatCoverage(null), '—');
  assert.equal(formatCoverage(0.391129), '39.11%');
});

test('external result required is distinct from failure and neutral unavailability', () => {
  assert.equal(statusPresentation('failed').label, 'Failed');
  assert.equal(statusPresentation('external_result_required').label, 'External result required');
  assert.equal(statusPresentation('unavailable').tone, 'neutral');
  assert.equal(statusPresentation('partial_success').label, 'Completed with warnings');
});

test('combined prediction status remains queued or running until a terminal result exists', () => {
  assert.equal(combinedPredictionStatus({ status: 'queued', ensemble: null }), 'Queued');
  assert.equal(combinedPredictionStatus({ status: 'running', ensemble: null }), 'Running');
  assert.equal(combinedPredictionStatus({ status: 'partial_success', ensemble: null }), 'Unavailable');
  assert.equal(combinedPredictionStatus({ status: 'success', ensemble: {
    status: 'success', score: 0, label: 'N', weights: { lreca: 0.5, fuzdrop: 0.5 }, threshold: 0.5,
    threshold_operator: '>=', calibration_status: 'not_calibrated',
    interpretation_status: 'experimental_weighted_score', reason: null,
  } }), 'Available');
});

test('unknown reason strings cannot leak arbitrary internal diagnostics', () => {
  assert.equal(explainReason('internal-private-path'), 'This result is currently unavailable.');
  assert.match(explainReason('fuzdrop_global_score_missing'), /does not include a global/);
});

test('5000 residue rows are paged without filtering, rounding or sorting data', () => {
  const rows = Array.from({ length: 5000 }, (_, index) => ({ position: index + 1, score: 0.123456789 }));
  const first = paginateRows(rows, 0, 50);
  const final = paginateRows(rows, 99, 50);
  assert.equal(first.rows.length, 50);
  assert.equal(first.pages, 100);
  assert.deepEqual([first.first, first.last], [1, 50]);
  assert.deepEqual([final.first, final.last], [4951, 5000]);
  assert.equal(final.rows[49].position, 5000);
  assert.equal(final.rows[49].score, 0.123456789);
  assert.equal(rows.length, 5000);
});

test('pagination clamps stale page state when a shorter result replaces the view', () => {
  assert.equal(paginateRows([1, 2, 3], 99).page, 0);
  assert.deepEqual(paginateRows([1, 2, 3], -1).rows, [1, 2, 3]);
  assert.deepEqual(paginateRows([]).rows, []);
  assert.deepEqual([paginateRows([]).first, paginateRows([]).last], [0, 0]);
});
