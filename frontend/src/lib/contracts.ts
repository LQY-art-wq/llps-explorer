/** Public Module 5 HTTP DTOs. Scientific values are retained exactly as received. */
export type MethodId = 'lreca' | 'fuzdrop' | 'seg' | 'dismeta';
export type AutomaticMethodId = 'lreca' | 'seg';
export type PredictionMode = 'independent' | 'weighted';
export type IntegrationMode = 'local_automatic' | 'remote_automatic' | 'manual_import' | 'integration_blocked';
export type SemanticType = 'model_prediction' | 'model_attribution' | 'derived_hotspot' | 'residue_propensity' | 'region_prediction' | 'region_annotation';
export type JobStatus = 'queued' | 'running' | 'success' | 'partial_success' | 'failed' | 'interrupted' | 'unavailable' | 'external_result_required';
export type ExecutionStatus = 'queued' | 'running' | 'success' | 'failed' | 'unavailable' | 'external_result_required' | 'skipped';
export type Label = 'P' | 'N';
export type Weights = { lreca: number; fuzdrop: number };
export interface MethodDescriptor {
  id: MethodId;
  name: string;
  display_name: string | null;
  category: 'prediction' | 'annotation';
  available: boolean;
  method_supported: boolean;
  automatic_analysis_available: boolean;
  integration_status: 'ready' | 'manual_import_only' | 'blocked' | 'unavailable';
  integration_mode: IntegrationMode;
  capabilities: ('global_score' | 'residue_attribution' | 'critical_regions' | 'residue_propensity' | 'regions' | 'low_complexity_regions' | 'disorder_regions')[];
  semantic_types: SemanticType[];
  manual_import_available: boolean;
  manual_import_supported: boolean | null;
  official_site_url: string | null;
  reason: string | null;
  message: string | null;
}
export interface AnalysisRequest {
  sequence: string;
  sequence_name?: string | null;
  selected_methods: MethodId[];
  prediction_mode?: PredictionMode;
  weights?: Weights | null;
  external_results?: { fuzdrop?: { result_id: string } };
}
export interface StructuredError { code: string; message: string }
export interface Region { start: number; end: number; length: number }
export interface ResidueAttribution {
  position: number;
  aa: string;
  score: number;
  semantic_type: 'model_attribution';
}
export interface TopResidue extends ResidueAttribution { rank: number }
export interface LRECACriticalRegion extends Region {
  score: number;
  is_primary: boolean;
  semantic_type: 'derived_hotspot';
}
export interface LRECAKDE {
  status: 'success' | 'unavailable';
  semantic_type: 'derived_hotspot';
  values: number[] | null;
  values_semantics: string;
  prominence: number;
  regions: LRECACriticalRegion[] | null;
  bandwidth: number | null;
  reason: string | null;
  warnings: string[];
  input_precision: 'official_csv_4_decimal_places' | null;
  runtime_ms: number | null;
}
export interface PublicLRECAModelMetadata {
  repository: 'https://github.com/ai-phasepro/LRECA';
  commit: string;
  model_variant: 'human_specific';
  dataset5_mapping_status: 'unconfirmed';
  checkpoint: string;
  checkpoint_sha256: string;
  checkpoint_size_bytes: number;
}
export interface LRECAResult {
  method_id: 'lreca'; method: 'lreca'; status: 'success'; message: null;
  semantic_type: 'model_prediction';
  model_variant: 'human_specific'; dataset5_mapping_status: 'unconfirmed';
  repository_commit: string; checkpoint: string; checkpoint_sha256: string;
  metadata: PublicLRECAModelMetadata;
  sequence: string; sequence_length: number;
  raw_score: number; calibrated_score: number; calibration_status: 'not_calibrated';
  score_semantics: 'uncalibrated_positive_class_softmax'; positive_class_index: 1;
  threshold: number; threshold_operator: '>'; logits: [number, number]; label: Label;
  device: 'cpu' | 'cuda' | `cuda:${number}`; runtime_ms: number;
  attribution_status: 'success' | 'unavailable' | 'not_requested';
  attribution_reason: string | null;
  attribution_semantic_type: 'model_attribution';
  attribution_normalization: 'official_absolute_maximum_diverging_scale';
  attribution_target_class_index: 0 | 1 | null;
  attribution_target_label: Label | null;
  residue_attribution: ResidueAttribution[] | null;
  top_residues: TopResidue[] | null;
  kde: LRECAKDE | null;
  critical_regions: LRECACriticalRegion[] | null;
  warnings: string[];
  timings_ms: Record<string, number> | null;
}
export interface FuzDropResiduePropensity {
  position: number; aa: string; score: number | null; score_name: 'pDP';
  Sbind: number | null; semantic_type: 'residue_propensity';
  Sbind_semantics: 'binding_mode_entropy';
}
export interface FuzDropRegion extends Region {
  type: 'droplet_promoting_region' | 'aggregation_hotspot';
  official_type: 'Droplet-promoting region' | 'Aggregation hot-spot';
  semantic_type: 'region_prediction';
}
export interface FuzDropResult {
  method_id: 'fuzdrop'; method: 'fuzdrop'; status: 'success'; message: null;
  mode: 'A' | 'B' | 'C' | 'D';
  integration_mode: 'documented_api' | 'supported_http_service' | 'browser_protected' | 'unknown';
  semantic_type: 'model_prediction'; sequence: string; sequence_length: number;
  raw_score: number | null; calibrated_score: number | null;
  calibration_status: 'not_calibrated'; score_semantics: 'official_pLLPS';
  label: Label | null; label_semantics: string | null;
  threshold: 0.6 | null; threshold_operator: '>=' | null;
  residue_propensity: FuzDropResiduePropensity[] | null;
  regions: FuzDropRegion[] | null;
  source: 'manual_import_of_official_result' | 'official_remote_service';
  source_declaration: 'official_fuzdrop_export' | null;
  origin_verification: 'user_declared_not_independently_verified' | 'official_service_response';
  coordinate_system: 'one_based_inclusive';
  coordinate_verification: 'user_declared_not_independently_verified' | 'verified_official_contract';
  official_site_url: string; service_version: string | null;
  retrieved_at: string | null; imported_at: string | null;
  sequence_sha256: string;
  raw_tsv_sha256: Partial<Record<'scores_tsv' | 'regions_tsv', string>>;
  raw_response_sha256: string | null;
  runtime_ms: number; runtime_scope: 'local_import_parsing' | 'official_remote_request';
  warnings: string[];
}
export interface FuzDropImportRequest {
  sequence: string;
  source_declaration: 'official_fuzdrop_export';
  coordinate_system: 'one_based_inclusive';
  scores_tsv?: string | null;
  regions_tsv?: string | null;
  pLLPS?: number | null;
  retrieved_at?: string | null;
}
export interface FuzDropImportResponse extends FuzDropResult {
  result_id: string; expires_at: string; validation_status: 'valid';
}
export interface SEGParameters {
  window: number; locut: number; hicut: number;
  input_format: 'fasta'; output_format: 'interval'; parse_seqids: false;
}
export interface SEGRegion extends Region { semantic_type: 'region_annotation' }
/** An annotation has no prediction score, threshold, or P/N fields. */
export interface SEGResult {
  method_id: 'seg'; method: 'seg'; status: 'success'; message: null;
  annotation_type: 'LCR'; semantic_type: 'region_annotation'; implementation: 'NCBI segmasker';
  version: string; application_version: string; executable_sha256: string | null;
  sequence_length: number; sequence_sha256: string;
  regions: SEGRegion[]; parameters: SEGParameters; runtime_ms: number;
  coverage: number; region_count: number; longest_region: number;
}
export interface MethodExecution {
  method: MethodId; status: ExecutionStatus; integration_mode: IntegrationMode;
  runtime_ms: number; result: LRECAResult | FuzDropResult | SEGResult | null;
  error: StructuredError | null; reason: string | null; warnings: string[];
}
export interface EnsembleResult {
  status: 'success' | 'unavailable'; score: number | null; label: Label | null;
  weights: Weights; threshold: number; threshold_operator: '>=';
  calibration_status: 'not_calibrated'; interpretation_status: 'experimental_weighted_score';
  reason: string | null;
}
export interface AnalysisJob {
  job_id: string; created_at: string; updated_at: string; expires_at: string;
  completed_at?: string | null;
  result_schema_version: '1.0';
  /** Returned by persisted-detail reads. The initial 202 response may omit it. */
  normalized_sequence?: string | null;
  status: JobStatus; sequence: { name: string | null; length: number; sha256: string };
  selected_methods: MethodId[]; prediction_mode: PredictionMode; weights: Weights | null;
  methods: Partial<Record<MethodId, MethodExecution>>;
  ensemble: EnsembleResult | null; warnings: string[];
}
export interface InputSnapshot {
  rawSequence: string; canonical: string; sequenceName: string | null;
  length: number; validResidues: number; inputType: 'raw' | 'fasta' | 'persisted'; submittedAt: string;
}
export interface AnalysisHistoryItem {
  job_id: string;
  sequence_name: string | null;
  sequence_length: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  expires_at: string;
  status: JobStatus;
  selected_methods: MethodId[];
  prediction_mode: PredictionMode;
  lreca_score: number | null;
  fuzdrop_score: number | null;
  ensemble_score: number | null;
  result_schema_version: '1.0';
}

export interface AnalysisHistoryPage {
  items: AnalysisHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface PublicConfig { analysis_retention_days: number }
export type AnalysisExportKind = 'json' | 'summary.csv' | 'residues.csv' | 'regions.csv' | 'fasta';
