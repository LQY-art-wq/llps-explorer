/** Test-only render fixtures. Never used to populate the normal analysis workspace. */
import type {
  AnalysisJob, FuzDropRegion, FuzDropResult, InputSnapshot, LRECACriticalRegion,
  LRECAResult, MethodExecution, Region, SEGResult,
} from "./contracts.ts";
import { sequenceSha256 } from "./sequence.ts";

export const FEATURE_TEST_LENGTHS = [100, 500, 1000, 2000, 5000] as const;
export type FeatureTestLength = typeof FEATURE_TEST_LENGTHS[number];
export const FEATURE_TEST_SCENARIOS = ["mixed", "malformed_fuzdrop_residue"] as const;
export type FeatureTestScenario = typeof FEATURE_TEST_SCENARIOS[number];
export const FEATURE_TEST_NOTICE =
  "Synthetic test data — rendering and coordinate tests only. No model inference, official prediction, or biological validation.";
const WARNING = "SYNTHETIC_TEST_DATA: render-only fixture; not a scientific result.";
const CREATED_AT = "2026-09-03T00:00:00.000Z";
const ALPHABET = "ACDEFGHIKLMNPQRSTVWY";

export interface FeatureTestFixture {
  kind: "synthetic_render_fixture";
  notice: string;
  length: FeatureTestLength;
  revision: number;
  scenario: FeatureTestScenario;
  job: AnalysisJob;
  input: InputSnapshot;
}

export interface FeaturePerformanceSample {
  kind: "initial_render" | "zoom" | "hover";
  durationMs: number;
}

export function summarizeFeaturePerformance(samples: readonly FeaturePerformanceSample[]) {
  return (["initial_render", "zoom", "hover"] as const).map((kind) => {
    const values = samples.filter((sample) => sample.kind === kind &&
      Number.isFinite(sample.durationMs) && sample.durationMs >= 0)
      .map((sample) => sample.durationMs).sort((a, b) => a - b);
    const count = values.length;
    return {
      kind, count,
      medianMs: count ? (values[Math.floor((count - 1) / 2)] + values[Math.floor(count / 2)]) / 2 : null,
      p95Ms: count ? values[Math.ceil(count * 0.95) - 1] : null,
      maxMs: count ? values[count - 1] : null,
    };
  });
}

/** Only an explicit server setting enables the otherwise unavailable test route. */
export function featureViewerTestEnabled(value: string | undefined): boolean {
  return value === "1";
}

function region(start: number, end: number): Region {
  return { start, end, length: end - start + 1 };
}

function execution(result: LRECAResult | FuzDropResult | SEGResult): MethodExecution {
  return {
    method: result.method, status: "success",
    integration_mode: result.method === "fuzdrop" ? "manual_import" : "local_automatic",
    runtime_ms: 0, result, error: null, reason: null, warnings: [WARNING],
  };
}

export async function createFeatureTestFixture(
  requestedLength: number,
  revision = 1,
  scenario: FeatureTestScenario = "mixed",
): Promise<FeatureTestFixture> {
  if (!FEATURE_TEST_LENGTHS.some((length) => length === requestedLength)) {
    throw new RangeError("Choose one of the supported synthetic test lengths.");
  }
  if (!Number.isSafeInteger(revision) || revision < 1) {
    throw new RangeError("Synthetic fixture revision must be a positive safe integer.");
  }
  if (!FEATURE_TEST_SCENARIOS.includes(scenario)) {
    throw new RangeError("Choose one of the supported synthetic test scenarios.");
  }
  const length = requestedLength as FeatureTestLength;
  const sequence = ALPHABET.repeat(Math.ceil(length / ALPHABET.length)).slice(0, length);
  const hash = await sequenceSha256(sequence);
  const name = `Synthetic test data · ${length} aa`;
  const critical: LRECACriticalRegion[] = [
    { ...region(1, 1), score: 0.1, is_primary: false, semantic_type: "derived_hotspot" },
    { ...region(Math.floor(length * 0.28), Math.floor(length * 0.63)),
      score: 3.2, is_primary: true, semantic_type: "derived_hotspot" },
    { ...region(length - 10, length), score: 1.4, is_primary: false, semantic_type: "derived_hotspot" },
  ];
  const attribution = Array.from(sequence, (aa, index) => ({
    position: index + 1, aa, score: 0.5 + 0.45 * Math.sin((index + 1) / 19),
    semantic_type: "model_attribution" as const,
  }));
  const lreca: LRECAResult = {
    method_id: "lreca", method: "lreca", status: "success", message: null,
    semantic_type: "model_prediction", model_variant: "human_specific", dataset5_mapping_status: "unconfirmed",
    repository_commit: "0".repeat(40), checkpoint: "SYNTHETIC_RENDER_FIXTURE_NO_MODEL.pt",
    checkpoint_sha256: "0".repeat(64),
    metadata: {
      repository: "https://github.com/ai-phasepro/LRECA", commit: "0".repeat(40),
      model_variant: "human_specific", dataset5_mapping_status: "unconfirmed",
      checkpoint: "SYNTHETIC_RENDER_FIXTURE_NO_MODEL.pt", checkpoint_sha256: "0".repeat(64),
      checkpoint_size_bytes: 0,
    },
    sequence, sequence_length: length, raw_score: 0.75, calibrated_score: 0.75,
    calibration_status: "not_calibrated", score_semantics: "uncalibrated_positive_class_softmax",
    positive_class_index: 1, threshold: 0.5, threshold_operator: ">", logits: [0, Math.log(3)], label: "P",
    device: "cpu", runtime_ms: 0, attribution_status: "success", attribution_reason: null,
    attribution_semantic_type: "model_attribution", attribution_normalization: "official_absolute_maximum_diverging_scale",
    attribution_target_class_index: 1, attribution_target_label: "P", residue_attribution: attribution,
    top_residues: [...attribution].sort((a, b) => b.score - a.score || a.position - b.position)
      .slice(0, 10).map((residue, index) => ({ ...residue, rank: index + 1 })),
    kde: {
      status: "success", semantic_type: "derived_hotspot",
      values: Array.from({ length }, (_, index) => 0.35 + 1.4 * (0.5 + 0.5 * Math.cos((index + 1) / 41))),
      values_semantics: "maximum_smoothed_score_density_minus_smoothed_score_density",
      prominence: 0.1, regions: critical, bandwidth: 0.1, reason: null, warnings: [WARNING],
      input_precision: "official_csv_4_decimal_places", runtime_ms: 0,
    },
    critical_regions: critical, warnings: [WARNING], timings_ms: { global_ms: 0, attribution_ms: 0, kde_ms: 0 },
  };
  const residues = Array.from(sequence, (aa, index) => ({
    position: index + 1, aa, score: (index + 1) % 97 === 0 ? null : ((index + 1) % 23) / 22,
    score_name: "pDP" as const, Sbind: ((index + 1) % 9) / 4,
    semantic_type: "residue_propensity" as const, Sbind_semantics: "binding_mode_entropy" as const,
  }));
  const fuzRegions: FuzDropRegion[] = [
    { ...region(1, 1), type: "droplet_promoting_region", official_type: "Droplet-promoting region", semantic_type: "region_prediction" },
    { ...region(Math.floor(length * 0.4), Math.floor(length * 0.62)), type: "droplet_promoting_region", official_type: "Droplet-promoting region", semantic_type: "region_prediction" },
    { ...region(Math.floor(length * 0.5), Math.floor(length * 0.7)), type: "aggregation_hotspot", official_type: "Aggregation hot-spot", semantic_type: "region_prediction" },
    { ...region(length, length), type: "aggregation_hotspot", official_type: "Aggregation hot-spot", semantic_type: "region_prediction" },
  ];
  // Exact duplicates and overlapping types are intentional coordinate/identity fixtures.
  fuzRegions.push({ ...fuzRegions[2] });
  const scoresTSV = "position\tresidue\tpDP\tSbind\n" + residues.map((row) =>
    `${row.position}\t${row.aa}\t${row.score ?? "undefined"}\t${row.Sbind}`,
  ).join("\n") + "\n";
  const regionsTSV = "type\tstart\tend\n" + fuzRegions.map((row) =>
    `${row.official_type}\t${row.start}\t${row.end}`,
  ).join("\n") + "\n";
  const fuzdrop: FuzDropResult = {
    method_id: "fuzdrop", method: "fuzdrop", status: "success", message: null,
    mode: "C", integration_mode: "browser_protected", semantic_type: "model_prediction",
    sequence, sequence_length: length, raw_score: 0.68, calibrated_score: 0.68,
    calibration_status: "not_calibrated", score_semantics: "official_pLLPS", label: "P",
    label_semantics: "SYNTHETIC_RENDER_FIXTURE_ONLY", threshold: 0.6, threshold_operator: ">=",
    residue_propensity: residues, regions: fuzRegions, source: "manual_import_of_official_result",
    source_declaration: "official_fuzdrop_export", origin_verification: "user_declared_not_independently_verified",
    coordinate_system: "one_based_inclusive", coordinate_verification: "user_declared_not_independently_verified",
    official_site_url: "https://fuzdrop.bio.unipd.it/predictor", service_version: null,
    retrieved_at: null, imported_at: CREATED_AT, sequence_sha256: hash,
    raw_tsv_sha256: {
      scores_tsv: await sequenceSha256(scoresTSV), regions_tsv: await sequenceSha256(regionsTSV),
    },
    raw_response_sha256: null, runtime_ms: 0, runtime_scope: "local_import_parsing", warnings: [WARNING],
  };
  if (scenario === "malformed_fuzdrop_residue") {
    // Intentional in-memory corruption, never an import payload or scientific response.
    // The production mapper must reject only this track and retain the other five.
    residues[Math.floor(length / 2)].position = 0;
    fuzdrop.warnings.push("SYNTHETIC_TEST_DATA: one pDP row intentionally has invalid position 0.");
  }
  const segRegions = [region(1, 5), region(Math.floor(length * 0.45), Math.floor(length * 0.55)), region(length, length)]
    .map((value) => ({ ...value, semantic_type: "region_annotation" as const }));
  const seg: SEGResult = {
    method_id: "seg", method: "seg", status: "success", message: null,
    annotation_type: "LCR", semantic_type: "region_annotation", implementation: "NCBI segmasker",
    version: "2.17.0", application_version: "1.0.0", executable_sha256: null,
    sequence_length: length, sequence_sha256: hash, regions: segRegions,
    parameters: { window: 12, locut: 2.2, hicut: 2.5, input_format: "fasta", output_format: "interval", parse_seqids: false },
    runtime_ms: 0, coverage: segRegions.reduce((total, item) => total + item.length, 0) / length,
    region_count: segRegions.length, longest_region: Math.max(...segRegions.map((item) => item.length)),
  };
  const job: AnalysisJob = {
    job_id: `analysis_synthetic_render_${scenario}_${length}_${revision}`, created_at: CREATED_AT, updated_at: CREATED_AT,
    expires_at: "2100-01-01T00:00:00.000Z", status: "success",
    sequence: { name, length, sha256: hash }, selected_methods: ["lreca", "fuzdrop", "seg"],
    prediction_mode: "independent", weights: null,
    methods: { lreca: execution(lreca), fuzdrop: execution(fuzdrop), seg: execution(seg) },
    ensemble: null, warnings: [WARNING], result_schema_version: "1.0",
  };
  return {
    kind: "synthetic_render_fixture", notice: FEATURE_TEST_NOTICE, length, revision, scenario, job,
    input: { rawSequence: sequence, canonical: sequence, sequenceName: name, length,
      validResidues: length, inputType: "raw", submittedAt: CREATED_AT },
  };
}
