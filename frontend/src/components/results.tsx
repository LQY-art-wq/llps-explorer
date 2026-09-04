'use client';

import { useId, useMemo, useReducer, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import type {
  AnalysisExportKind, AnalysisJob, FuzDropImportResponse, FuzDropRegion, FuzDropResiduePropensity, FuzDropResult, InputSnapshot,
  LRECACriticalRegion, LRECAResult, MethodDescriptor, MethodExecution, SEGRegion, SEGResult,
} from '../lib/contracts.ts';
import type { SequenceResidue } from '../lib/sequence-viewer-model.ts';
import {
  displayedFuzDrop, explainReason, formatCoverage, formatNumber, nativeResults, paginateRows,
  statusPresentation,
} from '../lib/viewer-data.ts';
import type { ViewerRegionSelection } from '../lib/viewer-data.ts';
import { ProteinFeatureViewer } from './protein-feature-viewer';
import { ProteinSequenceViewer } from './protein-sequence-viewer';
import { combinedPredictionStatus } from './result-status.ts';
import { buildFeatureViewerModel } from '../lib/feature-viewer-model.ts';
import { buildSequenceViewerModel } from '../lib/sequence-viewer-model.ts';
import {
  createViewerSelectionState, reduceViewerSelection,
} from '../lib/viewer-selection.ts';
import type { ResultTab, ViewerDestination } from '../lib/viewer-selection.ts';

export interface ResultsWorkspaceProps {
  job: AnalysisJob | null;
  submittedInput: InputSnapshot | null;
  imported: FuzDropImportResponse | null;
  methods: MethodDescriptor[];
  sessionRevision: number;
  onImport: () => void;
  onDownload: (jobId: string, kind: AnalysisExportKind) => Promise<boolean>;
  onOpenOfficial?: () => void;
}

const TABS = [
  ['overview', 'Overview'], ['features', 'Feature Viewer'], ['sequence', 'Sequence Viewer'],
  ['lreca', 'LRECA'], ['fuzdrop', 'FuzDrop'], ['annotations', 'Annotations'],
  ['tables', 'Tables'], ['download', 'Download'],
] as const;
type TabId = ResultTab;

function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className="badge" data-tone={tone}>{children}</span>;
}

function StatusBadge({ execution }: { execution?: MethodExecution }) {
  const status = statusPresentation(execution?.status);
  return <Badge tone={status.tone}>{status.label}</Badge>;
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div className="metric"><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong></div>;
}

function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty-state"><h3>{title}</h3>{children && <div className="muted">{children}</div>}</div>;
}

function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return <ul className="notice result-warnings">{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>;
}

function displayDate(value: string | null | undefined): string {
  if (!value || !Number.isFinite(new Date(value).getTime())) return '—';
  return new Intl.DateTimeFormat('en', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(value));
}

function executionExplanation(execution: MethodExecution | undefined): string {
  if (!execution) return 'This method was not selected for the submitted analysis.';
  if (execution.status === 'queued') return 'Waiting to begin this method.';
  if (execution.status === 'running') return 'Analysis is in progress. Results will appear when ready.';
  if (execution.status === 'skipped') return 'This method was skipped.';
  return explainReason(execution.error?.code ?? execution.reason);
}

interface Column<T> {
  key: string; label: string; render: (row: T) => ReactNode;
  sortValue?: (row: T) => number | string | null;
}
function ViewerLinks({ onFeature, onSequence }: {
  onFeature: () => void; onSequence: () => void;
}) {
  return <div className="button-group">
    <button className="text-button" type="button" onClick={onFeature}>View in Feature</button>
    <button className="text-button" type="button" onClick={onSequence}>View in Sequence</button>
  </div>;
}
function DataTable<T>({ title, rows, columns, missing, pageSize = 20, onRowActivate, rowLabel }: {
  title: string; rows: readonly T[] | null; columns: Column<T>[]; missing: string; pageSize?: number;
  onRowActivate?: (row: T) => void; rowLabel?: (row: T) => string;
}) {
  const [requestedPage, setPage] = useState(0);
  const [sort, setSort] = useState<{ key: string; direction: 'ascending' | 'descending' } | null>(null);
  const ordered = useMemo(() => {
    if (!rows || !sort) return rows ?? [];
    const column = columns.find((item) => item.key === sort.key);
    if (!column?.sortValue) return rows;
    return rows.map((row, index) => ({ row, index })).sort((a, b) => {
      const left = column.sortValue!(a.row), right = column.sortValue!(b.row);
      if (left === right) return a.index - b.index;
      if (left === null) return 1;
      if (right === null) return -1;
      const result = typeof left === 'number' && typeof right === 'number'
        ? left - right : String(left).localeCompare(String(right));
      return sort.direction === 'ascending' ? result : -result;
    }).map((item) => item.row);
  }, [columns, rows, sort]);
  const visible = paginateRows(ordered, requestedPage, pageSize);
  const { total, pages, page } = visible;
  function toggleSort(column: Column<T>) {
    if (!column.sortValue) return;
    setPage(0);
    setSort((current) => current?.key === column.key
      ? { key: column.key, direction: current.direction === 'ascending' ? 'descending' : 'ascending' }
      : { key: column.key, direction: 'ascending' });
  }
  return (
    <section className="panel">
      <div className="panel-header"><h3>{title}</h3>{rows !== null && <Badge>{total.toLocaleString()} rows</Badge>}</div>
      {rows === null ? <p className="muted">{missing}</p> : !rows.length ? <p className="muted">No entries were returned.</p> : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <caption className="sr-only">{title}; positions and region endpoints are 1-based inclusive.</caption>
              <thead><tr>{columns.map((column) => <th key={column.key} scope="col"
                aria-sort={sort?.key === column.key ? sort.direction : column.sortValue ? 'none' : undefined}>
                {column.sortValue ? <button className="table-sort" type="button" onClick={() => toggleSort(column)}>
                  {column.label}<span aria-hidden="true">{sort?.key === column.key ? sort.direction === 'ascending' ? ' ↑' : ' ↓' : ' ↕'}</span>
                </button> : column.label}</th>)}</tr></thead>
              <tbody>{visible.rows.map((row, index) => (
                <tr key={`${page}-${index}`} className={onRowActivate ? 'selectable-row' : undefined}
                  tabIndex={onRowActivate ? 0 : undefined} aria-label={rowLabel?.(row)}
                  onClick={(event) => {
                    if (!(event.target as HTMLElement).closest('button, a, input, select, summary')) onRowActivate?.(row);
                  }}
                  onKeyDown={(event) => { if (event.key === 'Enter' && event.target === event.currentTarget) onRowActivate?.(row); }}>
                  {columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
          {pages > 1 && <div className="table-pagination">
            <span className="muted" aria-live="polite">{visible.first}–{visible.last} of {total.toLocaleString()}</span>
            <div className="button-group">
              <button className="button" type="button" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label={`Previous page of ${title}`}>Previous</button>
              <button className="button" type="button" disabled={page === pages - 1} onClick={() => setPage(page + 1)} aria-label={`Next page of ${title}`}>Next</button>
            </div>
          </div>}
        </>
      )}
    </section>
  );
}

function ProteinInformation({ job, input }: { job: AnalysisJob; input: InputSnapshot | null }) {
  return <section className="panel">
    <div className="panel-header"><div><p className="eyebrow">SUBMITTED PROTEIN</p><h2>Protein Information</h2></div><Badge>{job.prediction_mode === 'weighted' ? 'Weighted' : 'Independent'}</Badge></div>
    <dl className="info-grid">
      <div><dt>Sequence name</dt><dd>{job.sequence.name || 'Unnamed protein'}</dd></div>
      <div><dt>Length</dt><dd>{job.sequence.length.toLocaleString()} aa</dd></div>
      <div><dt>Valid residues</dt><dd>{job.sequence.length.toLocaleString()} / {job.sequence.length.toLocaleString()}</dd></div>
      <div><dt>Input type</dt><dd>{input ? input.inputType === 'fasta' ? 'FASTA'
        : input.inputType === 'persisted' ? 'Persisted canonical sequence' : 'Raw sequence' : '—'}</dd></div>
      <div><dt>Analysis time</dt><dd><time dateTime={job.updated_at}>{displayDate(job.updated_at)}</time></dd></div>
      <div className="info-wide"><dt>Job ID</dt><dd className="mono">{job.job_id}</dd></div>
    </dl>
  </section>;
}

function SequenceInformationCard({ job, input }: { job: AnalysisJob; input: InputSnapshot | null }) {
  return <section className="panel" data-tone="neutral">
    <div className="panel-header"><div><h3>Sequence Information</h3><p className="muted small">Submitted sequence</p></div><Badge>Input</Badge></div>
    <div className="metrics-grid">
      <Metric label="Length (aa)" value={job.sequence.length.toLocaleString()} />
      <Metric label="Valid residues" value={job.sequence.length.toLocaleString()} />
      <Metric label="Input type" value={input ? input.inputType === 'fasta' ? 'FASTA'
        : input.inputType === 'persisted' ? 'Persisted canonical' : 'Raw' : '—'} />
    </div>
  </section>;
}

function LRECACard({ result, execution }: { result: LRECAResult | null; execution?: MethodExecution }) {
  return <section className="panel score-card" data-tone="lreca">
    <div className="panel-header"><div><h3>LRECA</h3><p className="muted small">Human-specific model</p></div><StatusBadge execution={execution} /></div>
    <div className="score-value">{formatNumber(result?.raw_score)}</div>
    <p className="score-label">{result ? `${result.label} · ${result.label === 'P' ? 'Positive' : 'Negative'}` : 'Global score'}</p>
    {result ? <><p className="muted small">Threshold {result.threshold_operator} {formatNumber(result.threshold, 2)}</p><p className="muted small">Uncalibrated model score</p></> : <p className="muted small">{execution ? executionExplanation(execution) : 'Run LRECA to view a global prediction and residue attribution.'}</p>}
  </section>;
}

function FuzDropActions({ onImport, onOpenOfficial, importDisabled = false }: Pick<ResultsWorkspaceProps, 'onImport' | 'onOpenOfficial'> & { importDisabled?: boolean }) {
  return <div className="button-group">
    <button className="button primary" type="button" onClick={onImport} disabled={importDisabled}>Import result</button>
    {onOpenOfficial ? <button className="button" type="button" onClick={onOpenOfficial}>Open Official FuzDrop <span aria-hidden="true">↗</span></button>
      : <a className="button" href="https://fuzdrop.bio.unipd.it/predictor" target="_blank" rel="noopener noreferrer">Open Official FuzDrop <span aria-hidden="true">↗</span></a>}
  </div>;
}

function FuzDropCard({ result, execution, onImport, onOpenOfficial, preview = false, importDisabled = false }: {
  result: FuzDropResult | null; execution?: MethodExecution; preview?: boolean; importDisabled?: boolean;
} & Pick<ResultsWorkspaceProps, 'onImport' | 'onOpenOfficial'>) {
  return <section className="panel score-card" data-tone="fuzdrop">
    <div className="panel-header"><div><h3>FuzDrop</h3><p className="muted small">{preview ? 'Imported result preview' : 'Imported official result'}</p></div>{result ? <Badge tone="fuzdrop">Imported</Badge> : <StatusBadge execution={execution} />}</div>
    <div className="score-value">{formatNumber(result?.raw_score)}</div>
    <p className="score-label">{result?.label ? `${result.label} · ${result.label === 'P' ? 'Positive' : 'Negative'}` : 'Global pLLPS'}</p>
    {result ? <>
      <p className="muted small">{result.raw_score === null ? 'A global pLLPS score was not included in this import.' : `Driver threshold ${result.threshold_operator} ${formatNumber(result.threshold, 2)}`}</p>
      <p className="muted small">{result.label === 'N' ? 'N means the driver threshold was not reached.' : 'Source declared by the user; not independently authenticated.'}</p>
    </> : <><p className="muted small">{execution ? executionExplanation(execution) : 'No FuzDrop result is included in this analysis.'}</p><FuzDropActions onImport={onImport} onOpenOfficial={onOpenOfficial} importDisabled={importDisabled} /></>}
  </section>;
}

function CombinedCard({ job }: { job: AnalysisJob }) {
  const result = job.ensemble;
  const pending = job.status === 'queued' || job.status === 'running';
  return <section className="panel score-card combined-card" data-tone="neutral">
    <div className="panel-header"><h3>Combined Score</h3><Badge>Experimental weighted score</Badge></div>
    <div className="score-value">{formatNumber(result?.score)}</div>
    <p className="score-label">{result?.status === 'success' && result.label ? `${result.label} · ${result.label === 'P' ? 'Positive' : 'Negative'}` : pending ? 'Awaiting results' : 'Unavailable'}</p>
    {result && <p className="muted small">Threshold {result.threshold_operator} {formatNumber(result.threshold, 2)}</p>}
    {result?.status === 'unavailable' && <p className="muted small">{explainReason(result.reason)}</p>}
    <p className="muted small">Scores are combined without cross-method probability calibration.</p>
    {job.weights && <p className="muted small">LRECA {formatNumber(job.weights.lreca * 100, 1)}% · FuzDrop {formatNumber(job.weights.fuzdrop * 100, 1)}%</p>}
  </section>;
}

function SEGSummary({ result, execution, hasSubmittedJob }: { result: SEGResult | null; execution?: MethodExecution; hasSubmittedJob: boolean }) {
  return <section className="panel" data-tone="seg">
    <div className="panel-header"><div><h3>Low-complexity Regions</h3><p className="muted small">SEG · sequence annotation</p></div>{hasSubmittedJob ? <StatusBadge execution={execution} /> : <Badge>Not run</Badge>}</div>
    <div className="metrics-grid">
      <Metric label="LCR coverage" value={formatCoverage(result?.coverage)} />
      <Metric label="Region count" value={result?.region_count.toLocaleString() ?? '—'} />
      <Metric label="Longest region" value={result ? `${result.longest_region.toLocaleString()} aa` : '—'} />
    </div>
    {!result && <p className="muted small">{execution ? executionExplanation(execution) : 'Run SEG to view low-complexity regions.'}</p>}
  </section>;
}

function DisMetaUnavailable() {
  return <section className="panel" data-tone="neutral"><div className="panel-header"><div><h3>Intrinsically Disordered Regions</h3><p className="muted small">DisMeta · IDR annotation</p></div><Badge>Unavailable</Badge></div><p className="muted">DisMeta integration is currently unavailable.</p></section>;
}

function LRECATables({ result, onSelectResidue, onSelectRegion, onViewResidue, onViewRegion }: {
  result: LRECAResult | null;
  onSelectResidue: (position: number) => void;
  onSelectRegion: (region: ViewerRegionSelection) => void;
  onViewResidue: (destination: ViewerDestination, position: number) => void;
  onViewRegion: (destination: ViewerDestination, region: ViewerRegionSelection) => void;
}) {
  return <>
    <DataTable title="LRECA Top Residues" rows={result?.top_residues ?? null} missing="Residue attribution is not available for this result."
      columns={[
        { key: 'rank', label: 'Rank', render: (row) => row.rank, sortValue: (row) => row.rank },
        { key: 'position', label: 'Position', render: (row) => row.position, sortValue: (row) => row.position },
        { key: 'aa', label: 'AA', render: (row) => row.aa, sortValue: (row) => row.aa },
        { key: 'score', label: 'Attribution Score', render: (row) => formatNumber(row.score, 4), sortValue: (row) => row.score },
        { key: 'viewers', label: 'Open in viewer', render: (row) => <ViewerLinks
          onFeature={() => onViewResidue('features', row.position)}
          onSequence={() => onViewResidue('sequence', row.position)} /> },
      ]} onRowActivate={(row) => onSelectResidue(row.position)}
      rowLabel={(row) => `Select LRECA residue ${row.aa}${row.position}`} />
    <DataTable<LRECACriticalRegion> title="LRECA Critical Regions" rows={result?.critical_regions ?? null} missing="KDE critical regions are not available for this result."
      columns={[
        { key: 'type', label: 'Type', render: () => 'KDE hotspot', sortValue: () => 'KDE hotspot' },
        { key: 'start', label: 'Start', render: (row) => row.start, sortValue: (row) => row.start },
        { key: 'end', label: 'End', render: (row) => row.end, sortValue: (row) => row.end },
        { key: 'length', label: 'Length', render: (row) => row.length, sortValue: (row) => row.length },
        { key: 'score', label: 'Score', render: (row) => formatNumber(row.score, 4), sortValue: (row) => row.score },
        { key: 'primary', label: 'Primary', render: (row) => row.is_primary ? <Badge tone="lreca">Yes</Badge> : 'No', sortValue: (row) => row.is_primary ? 1 : 0 },
        { key: 'viewers', label: 'Open in viewer', render: (row) => {
          const selected = { method: 'lreca', type: 'critical_region', start: row.start, end: row.end,
            semanticType: 'derived_hotspot' } as const;
          return <ViewerLinks onFeature={() => onViewRegion('features', selected)}
            onSequence={() => onViewRegion('sequence', selected)} />;
        } },
      ]} onRowActivate={(row) => onSelectRegion({ method: 'lreca', type: 'critical_region', start: row.start,
        end: row.end, semanticType: 'derived_hotspot' })}
      rowLabel={(row) => `Select LRECA critical region ${row.start} to ${row.end}`} />
  </>;
}

function FuzDropRegionTable({ result, onSelectRegion, onViewRegion }: {
  result: FuzDropResult | null;
  onSelectRegion?: (region: ViewerRegionSelection) => void;
  onViewRegion?: (destination: ViewerDestination, region: ViewerRegionSelection) => void;
}) {
  return <DataTable<FuzDropRegion> title="FuzDrop Regions" rows={result?.regions ?? null} missing="No region export was supplied."
    columns={[
        { key: 'type', label: 'Official region type', render: (row) => row.official_type, sortValue: (row) => row.official_type },
        { key: 'start', label: 'Start', render: (row) => row.start, sortValue: (row) => row.start },
        { key: 'end', label: 'End', render: (row) => row.end, sortValue: (row) => row.end },
        { key: 'length', label: 'Length', render: (row) => row.length, sortValue: (row) => row.length },
      ...(onViewRegion ? [{ key: 'viewers', label: 'Open in viewer', render: (row: FuzDropRegion) => {
        const selected: ViewerRegionSelection = { method: 'fuzdrop', type: row.type,
          start: row.start, end: row.end, semanticType: 'region_prediction' };
        return <ViewerLinks onFeature={() => onViewRegion('features', selected)}
          onSequence={() => onViewRegion('sequence', selected)} />;
      } }] : []),
    ]} onRowActivate={onSelectRegion ? (row) => onSelectRegion({ method: 'fuzdrop', type: row.type,
      start: row.start, end: row.end, semanticType: 'region_prediction' }) : undefined}
    rowLabel={(row) => `Select FuzDrop region ${row.start} to ${row.end}`} />;
}

function SEGRegionTable({ result, onSelectRegion, onViewRegion }: {
  result: SEGResult | null;
  onSelectRegion: (region: ViewerRegionSelection) => void;
  onViewRegion: (destination: ViewerDestination, region: ViewerRegionSelection) => void;
}) {
  return <DataTable<SEGRegion> title="SEG LCR Regions" rows={result?.regions ?? null} missing="LCR regions are not available for this result."
    columns={[
        { key: 'region', label: 'Region', render: (row) => `${row.start}–${row.end}` },
        { key: 'start', label: 'Start', render: (row) => row.start, sortValue: (row) => row.start },
        { key: 'end', label: 'End', render: (row) => row.end, sortValue: (row) => row.end },
        { key: 'length', label: 'Length', render: (row) => row.length, sortValue: (row) => row.length },
      { key: 'viewers', label: 'Open in viewer', render: (row) => {
        const selected = { method: 'seg', type: 'low_complexity_region', start: row.start,
          end: row.end, semanticType: 'region_annotation' } as const;
        return <ViewerLinks onFeature={() => onViewRegion('features', selected)}
          onSequence={() => onViewRegion('sequence', selected)} />;
        } },
      ]} onRowActivate={(row) => onSelectRegion({ method: 'seg', type: 'low_complexity_region',
        start: row.start, end: row.end, semanticType: 'region_annotation' })}
      rowLabel={(row) => `Select SEG region ${row.start} to ${row.end}`} />;
}

function PredictionSummaryTable({ job }: { job: AnalysisJob }) {
  const native = nativeResults(job);
  const rows: { method: string; score: number | null; label: string | null; status: string }[] = [];
  if (job.selected_methods.includes('lreca')) rows.push({ method: 'LRECA', score: native.lreca?.raw_score ?? null,
    label: native.lreca?.label ?? null, status: statusPresentation(job.methods.lreca?.status).label });
  if (job.selected_methods.includes('fuzdrop')) rows.push({ method: 'FuzDrop', score: native.fuzdrop?.raw_score ?? null,
    label: native.fuzdrop?.label ?? null, status: statusPresentation(job.methods.fuzdrop?.status).label });
  if (job.prediction_mode === 'weighted') rows.push({ method: 'Combined', score: job.ensemble?.score ?? null,
    label: job.ensemble?.label ?? null, status: combinedPredictionStatus(job) });
  return <DataTable title="Prediction Summary" rows={rows} missing="Prediction summary is unavailable." columns={[
    { key: 'method', label: 'Method', render: (row) => row.method },
    { key: 'score', label: 'Global Score', render: (row) => formatNumber(row.score, 6) },
    { key: 'label', label: 'Label', render: (row) => row.label ?? '—' },
    { key: 'status', label: 'Status', render: (row) => row.status },
  ]} />;
}

function valueOrStatus(value: number | null, status: string): ReactNode {
  return value === null ? status.replaceAll('_', ' ') : formatNumber(value, 6);
}

function FullResidueTable({ residues, onSelectResidue, onViewResidue }: {
  residues: readonly SequenceResidue[] | null;
  onSelectResidue: (position: number) => void;
  onViewResidue: (destination: ViewerDestination, position: number) => void;
}) {
  const [position, setPosition] = useState('');
  const [regionFilter, setRegionFilter] = useState<'all' | 'any' | 'lreca' | 'fuzdrop' | 'seg'>('all');
  const filtered = useMemo(() => {
    if (!residues) return null;
    const wanted = position.trim() ? Number(position) : null;
    return residues.filter((row) => {
      if (wanted !== null && (!Number.isSafeInteger(wanted) || row.position !== wanted)) return false;
      if (regionFilter === 'lreca') return row.lrecaCriticalMembership === 'primary' || row.lrecaCriticalMembership === 'candidate';
      if (regionFilter === 'fuzdrop') return row.fuzdropRegionMembership === 'yes';
      if (regionFilter === 'seg') return row.segMembership === 'yes';
      if (regionFilter === 'any') return row.lrecaCriticalMembership === 'primary' || row.lrecaCriticalMembership === 'candidate'
        || row.fuzdropRegionMembership === 'yes' || row.segMembership === 'yes';
      return true;
    });
  }, [position, regionFilter, residues]);
  return <section className="residue-table-section" aria-label="Residue-level data">
    <div className="residue-table-controls">
      <label>Find position<input className="input compact-input" inputMode="numeric" value={position}
        placeholder="1-based" onChange={(event) => setPosition(event.target.value)} /></label>
      <label>Region membership<select value={regionFilter}
        onChange={(event) => setRegionFilter(event.target.value as typeof regionFilter)}>
        <option value="all">All residues</option><option value="any">Any available region</option>
        <option value="lreca">LRECA critical region</option><option value="fuzdrop">FuzDrop region</option>
        <option value="seg">SEG LCR</option>
      </select></label>
    </div>
    <DataTable title="Residue-level Data" rows={filtered} missing="A validated persisted sequence is required."
      pageSize={50} onRowActivate={(row) => onSelectResidue(row.position)}
      rowLabel={(row) => `Select residue ${row.aa}${row.position}`} columns={[
        { key: 'position', label: 'Position', render: (row) => row.position, sortValue: (row) => row.position },
        { key: 'aa', label: 'AA', render: (row) => row.aa, sortValue: (row) => row.aa },
        { key: 'attribution', label: 'LRECA Attribution', render: (row) => valueOrStatus(row.lrecaAttribution, row.lrecaAttributionStatus),
          sortValue: (row) => row.lrecaAttribution },
        { key: 'kde', label: 'LRECA KDE', render: (row) => valueOrStatus(row.kdeDensity, row.kdeDensityStatus),
          sortValue: (row) => row.kdeDensity },
        { key: 'fuzdrop', label: 'FuzDrop Propensity', render: (row) => valueOrStatus(row.fuzdropPropensity, row.fuzdropPropensityStatus),
          sortValue: (row) => row.fuzdropPropensity },
        { key: 'lcr', label: 'SEG LCR', render: (row) => row.segMembership.replaceAll('_', ' ') },
        { key: 'critical', label: 'Critical Region', render: (row) => row.lrecaCriticalMembership.replaceAll('_', ' ') },
        { key: 'viewers', label: 'Open in viewer', render: (row) => <ViewerLinks
          onFeature={() => onViewResidue('features', row.position)} onSequence={() => onViewResidue('sequence', row.position)} /> },
      ]} />
  </section>;
}

function DownloadPanel({ job, onDownload }: { job: AnalysisJob | null; onDownload: ResultsWorkspaceProps['onDownload'] }) {
  const downloads: readonly { kind: AnalysisExportKind; label: string; primary?: boolean }[] = [
    { kind: 'json', label: 'Download JSON', primary: true },
    { kind: 'summary.csv', label: 'Download summary CSV' },
    { kind: 'residues.csv', label: 'Download residue CSV' },
    { kind: 'regions.csv', label: 'Download regions CSV' },
    { kind: 'fasta', label: 'Download FASTA' },
  ];
  return <section className="panel"><div className="panel-header"><div><p className="eyebrow">EXPORT</p>
    <h2>Download persisted results</h2></div><Badge>JSON · CSV · FASTA</Badge></div>
    <p className="muted">Files are generated from the versioned persisted result. CSV coordinates are 1-based and inclusive; exported scientific values retain backend precision.</p>
    <div className="download-actions">{downloads.map(({ kind, label, primary }) => <button key={kind}
      className={`button ${primary ? 'primary' : ''}`} type="button" disabled={!job}
      onClick={() => { if (job) void onDownload(job.job_id, kind); }}>{label}</button>)}</div>
    {!job && <p className="muted small">A saved analysis is required for download.</p>}
  </section>;
}

function SequenceSelectionPreview({ selectedResidue, selectedRegion, sequence, onOpen }: {
  selectedResidue: number | null;
  selectedRegion: ViewerRegionSelection | null;
  sequence: string | null;
  onOpen: () => void;
}) {
  return <section className="panel" aria-label="Sequence selection preview">
    <div className="panel-header"><div><p className="eyebrow">SEQUENCE SELECTION</p>
      <h2>Protein Sequence Viewer</h2></div><Badge>Compact preview</Badge></div>
    <p className="muted">The full amino-acid sequence and residue evidence are available in the Sequence Viewer tab.</p>
    {selectedResidue !== null ? <p role="status">Selected residue: <strong>{sequence?.[selectedResidue - 1]
      ? `${sequence[selectedResidue - 1]}${selectedResidue}` : selectedResidue}</strong></p>
      : selectedRegion ? <p role="status">Selected {selectedRegion.method.toUpperCase()} region: <strong>{selectedRegion.start}–{selectedRegion.end}</strong></p>
        : <p className="muted">No residue or region is selected.</p>}
    <button className="button" type="button" onClick={onOpen}>Open Sequence Viewer</button>
  </section>;
}

export function ResultsWorkspace(props: ResultsWorkspaceProps) {
  // Selection and table focus belong to a result, not to an editable input draft.
  return <ResultContent key={`${props.job?.job_id ?? props.imported?.result_id ?? 'empty'}:${props.sessionRevision}`} {...props} />;
}

function ResultContent({ job, submittedInput, imported, methods, onImport, onDownload, onOpenOfficial }: ResultsWorkspaceProps) {
  const [viewerState, dispatchViewer] = useReducer(
    reduceViewerSelection, undefined, () => createViewerSelectionState('overview'),
  );
  const {
    activeTab: active, selectedResidue, selectedRegion,
    featureFocusRequest, sequenceFocusRequest,
  } = viewerState;
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const native = nativeResults(job);
  const fuzdrop = displayedFuzDrop(job, imported);
  const featureModel = useMemo(() => buildFeatureViewerModel(job, submittedInput), [job, submittedInput]);
  const sequenceModel = useMemo(() => buildSequenceViewerModel(featureModel), [featureModel]);
  const status = statusPresentation(job?.status);
  const importDisabled = methods.find((method) => method.id === 'fuzdrop')?.manual_import_available !== true;

  function focusTab(destination: ViewerDestination) {
    tabRefs.current[destination === 'features' ? 1 : 2]?.focus();
  }
  function viewResidue(destination: ViewerDestination, position: number) {
    dispatchViewer({ type: 'view_residue', destination, position });
    focusTab(destination);
  }
  function viewRegion(destination: ViewerDestination, region: ViewerRegionSelection) {
    dispatchViewer({ type: 'view_region', destination, region });
    focusTab(destination);
  }
  function viewSelected(destination: ViewerDestination) {
    dispatchViewer({ type: 'view_selected', destination });
    focusTab(destination);
  }
  function rememberResidue(position: number) {
    dispatchViewer({ type: 'select_residue', position });
  }
  function rememberRegion(region: ViewerRegionSelection) {
    dispatchViewer({ type: 'select_region', region });
  }
  function clearSelection() { dispatchViewer({ type: 'clear' }); }
  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = TABS.length - 1;
    else return;
    event.preventDefault(); dispatchViewer({ type: 'set_tab', tab: TABS[next][0] });
    tabRefs.current[next]?.focus();
  }

  const featureViewer = <ProteinFeatureViewer model={featureModel} selectedResidue={selectedResidue}
    selectedRegion={selectedRegion} focusRequest={featureFocusRequest} onResidueSelect={rememberResidue}
    onRegionSelect={rememberRegion} onSelectionClear={clearSelection}
    onViewInSequence={() => viewSelected('sequence')} />;
  const compactFeatureViewer = <ProteinFeatureViewer model={featureModel} variant="compact"
    selectedResidue={selectedResidue} selectedRegion={selectedRegion} onResidueSelect={rememberResidue}
    onRegionSelect={rememberRegion} onSelectionClear={clearSelection}
    onOpenFull={() => viewSelected('features')} />;
  const sequenceViewer = <ProteinSequenceViewer model={sequenceModel}
    selectedResidue={selectedResidue} selectedRegion={selectedRegion}
    focusRequest={sequenceFocusRequest} active={active === 'sequence'}
    onResidueSelect={rememberResidue} onRegionSelect={rememberRegion}
    onSelectionClear={clearSelection} onViewInFeature={() => viewSelected('features')} />;
  const lrecaTables = <LRECATables result={native.lreca} onSelectResidue={rememberResidue}
    onSelectRegion={rememberRegion}
    onViewResidue={viewResidue} onViewRegion={viewRegion} />;

  function renderTab(tab: TabId) {
    if (tab === 'features') return featureViewer;
    if (tab === 'sequence') return sequenceViewer;
    if (tab === 'overview') return <>
      {job ? <>
        <ProteinInformation job={job} input={submittedInput} />
        {job.status === 'partial_success' && <div className="notice" role="status">Analysis completed with warnings. Successful results remain available below.</div>}
        <section aria-label="Prediction Summary"><div className="section-heading"><h2>Prediction Summary</h2><span className="muted small">Global prediction sources</span></div>
          <div className="result-grid">
            {job.prediction_mode === 'weighted' && <CombinedCard job={job} />}
            <LRECACard result={native.lreca} execution={job.methods.lreca} />
            <FuzDropCard result={native.fuzdrop} execution={job.methods.fuzdrop} onImport={onImport} onOpenOfficial={onOpenOfficial} importDisabled={importDisabled} />
            <SequenceInformationCard job={job} input={submittedInput} />
          </div>
        </section>
        <section className="panel"><div className="panel-header"><h2>Analysis Status</h2><Badge tone={status.tone}>{status.label}</Badge></div>
          <ul className="status-list">{job.selected_methods.map((method) => <li className="status-row" key={method}>
            <strong>{methods.find((item) => item.id === method)?.name ?? (method === 'lreca' ? 'LRECA' : method === 'seg' ? 'SEG' : method === 'fuzdrop' ? 'FuzDrop' : 'DisMeta')}</strong>
            <StatusBadge execution={job.methods[method]} />
            {job.methods[method]?.status !== 'success' && <span className="muted small">{executionExplanation(job.methods[method])}</span>}
          </li>)}</ul>
        </section>
        <WarningList warnings={job.warnings} />
      </> : <section className="panel"><EmptyState title="Ready to explore your protein"><p>Enter a sequence, choose available methods, and run an analysis to view predictions and annotations.</p><p>Your submitted results will appear here.</p></EmptyState></section>}
      {!job && imported && <FuzDropCard result={imported} preview onImport={onImport} onOpenOfficial={onOpenOfficial} importDisabled={importDisabled} />}
      <section aria-label="Annotation Summary"><div className="section-heading"><h2>Annotation Summary</h2><span className="muted small">Independent sequence features</span></div><div className="result-grid"><SEGSummary result={native.seg} execution={job?.methods.seg} hasSubmittedJob={job !== null} /><DisMetaUnavailable /></div></section>
      {compactFeatureViewer}
      <SequenceSelectionPreview selectedResidue={selectedResidue} selectedRegion={selectedRegion} sequence={sequenceModel.sequence}
        onOpen={() => viewSelected('sequence')} />
    </>;
    if (tab === 'lreca') return <>
      <LRECACard result={native.lreca} execution={job?.methods.lreca} />
      {native.lreca && <section className="panel"><div className="panel-header"><h2>Model & explanation</h2><Badge tone="lreca">Human-specific</Badge></div>
        <dl className="info-grid"><div><dt>Model variant</dt><dd>human_specific</dd></div><div><dt>Checkpoint</dt><dd className="mono">{native.lreca.checkpoint}</dd></div><div><dt>Attribution status</dt><dd>{native.lreca.attribution_status === 'not_requested' ? 'Not requested' : statusPresentation(native.lreca.attribution_status).label}</dd></div><div><dt>Attribution target</dt><dd>{native.lreca.attribution_target_label ?? '—'}</dd></div></dl>
        <p className="muted small">Grad-CAM attribution explains the model’s selected class. Critical regions are derived from the KDE procedure.</p>
        <WarningList warnings={native.lreca.warnings} />
      </section>}
      {lrecaTables}
    </>;
    if (tab === 'fuzdrop') return <>
      {!fuzdrop ? <section className="panel"><EmptyState title={job?.methods.fuzdrop?.status === 'failed' ? 'FuzDrop result unavailable' : 'No FuzDrop result imported'}><p>{job ? executionExplanation(job.methods.fuzdrop) : 'Import an official result to inspect its supplied scores and regions.'}</p></EmptyState><FuzDropActions onImport={onImport} onOpenOfficial={onOpenOfficial} importDisabled={importDisabled} /></section> : <>
        <FuzDropCard result={fuzdrop} preview={!job} execution={job?.methods.fuzdrop} onImport={onImport} onOpenOfficial={onOpenOfficial} importDisabled={importDisabled} />
        <section className="panel"><div className="panel-header"><h2>Import provenance</h2><Badge tone="fuzdrop">User-declared source</Badge></div><p className="muted">The import was validated for format and sequence identity. Its official origin and coordinate declaration are not independently authenticated.</p><dl className="info-grid"><div><dt>Imported</dt><dd>{displayDate(fuzdrop.imported_at)}</dd></div><div><dt>Official result retrieved</dt><dd>{displayDate(fuzdrop.retrieved_at)}</dd></div><div><dt>Coordinates</dt><dd>1-based inclusive, declared</dd></div><div><dt>Sequence length</dt><dd>{fuzdrop.sequence_length.toLocaleString()} aa</dd></div></dl><WarningList warnings={fuzdrop.warnings} /></section>
        <DataTable title="FuzDrop Residue Propensity" rows={fuzdrop.residue_propensity} missing="No residue score export was supplied." pageSize={50}
          onRowActivate={job ? (row) => rememberResidue(row.position) : undefined}
          rowLabel={(row) => `Select FuzDrop residue ${row.aa}${row.position}`} columns={[
          { key: 'position', label: 'Position', render: (row) => row.position, sortValue: (row) => row.position },
          { key: 'aa', label: 'AA', render: (row) => row.aa, sortValue: (row) => row.aa },
          { key: 'pDP', label: 'pDP propensity', render: (row) => formatNumber(row.score, 4), sortValue: (row) => row.score },
          { key: 'Sbind', label: 'Sbind entropy', render: (row) => formatNumber(row.Sbind, 4), sortValue: (row) => row.Sbind },
          ...(job ? [{ key: 'viewers', label: 'Open in viewer',
            render: (row: FuzDropResiduePropensity) => <ViewerLinks
              onFeature={() => viewResidue('features', row.position)}
              onSequence={() => viewResidue('sequence', row.position)} /> }] : []),
        ]} />
        <p className="muted small">pDP is a residue propensity, not LRECA attribution. Sbind describes binding-mode entropy, not probability.</p>
        <FuzDropRegionTable result={fuzdrop} onSelectRegion={job ? rememberRegion : undefined} onViewRegion={job ? viewRegion : undefined} />
      </>}
    </>;
    if (tab === 'annotations') return <><SEGSummary result={native.seg} execution={job?.methods.seg} hasSubmittedJob={job !== null} />
      <SEGRegionTable result={native.seg} onSelectRegion={rememberRegion} onViewRegion={viewRegion} /><DisMetaUnavailable /></>;
    if (tab === 'tables') return <><p className="muted small">All positions and region endpoints use 1-based inclusive coordinates. Values are displayed from the persisted normalized result without scientific recalculation.</p>
      {job && <PredictionSummaryTable job={job} />}{lrecaTables}
      <SEGSummary result={native.seg} execution={job?.methods.seg} hasSubmittedJob={job !== null} />
      <SEGRegionTable result={native.seg} onSelectRegion={rememberRegion} onViewRegion={viewRegion} />
      {fuzdrop && <><FuzDropCard result={fuzdrop} execution={job?.methods.fuzdrop} onImport={onImport}
        onOpenOfficial={onOpenOfficial} importDisabled={importDisabled} />
        {fuzdrop.residue_propensity !== null && <DataTable title="FuzDrop Residue Propensity" rows={fuzdrop.residue_propensity}
          missing="No residue score export was supplied." pageSize={50}
          onRowActivate={job ? (row) => rememberResidue(row.position) : undefined}
          rowLabel={(row) => `Select FuzDrop residue ${row.aa}${row.position}`} columns={[
            { key: 'position', label: 'Position', render: (row) => row.position, sortValue: (row) => row.position },
            { key: 'aa', label: 'AA', render: (row) => row.aa, sortValue: (row) => row.aa },
            { key: 'pDP', label: 'pDP propensity', render: (row) => formatNumber(row.score, 4), sortValue: (row) => row.score },
            { key: 'Sbind', label: 'Sbind entropy', render: (row) => formatNumber(row.Sbind, 4), sortValue: (row) => row.Sbind },
            ...(job ? [{ key: 'viewers', label: 'Open in viewer', render: (row: FuzDropResiduePropensity) => <ViewerLinks
              onFeature={() => viewResidue('features', row.position)} onSequence={() => viewResidue('sequence', row.position)} /> }] : []),
          ]} />}
        {fuzdrop.regions !== null && <FuzDropRegionTable result={fuzdrop}
          onSelectRegion={job ? rememberRegion : undefined} onViewRegion={job ? viewRegion : undefined} />}</>}
      <DisMetaUnavailable />
      <FullResidueTable residues={sequenceModel.sequence ? sequenceModel.residues : null}
        onSelectResidue={rememberResidue} onViewResidue={viewResidue} />
    </>;
    return <DownloadPanel job={job} onDownload={onDownload} />;
  }

  return <div className="results-workspace">
    <div className="result-context-bar"><span className="eyebrow">RESULTS</span>{job && <><strong>{job.sequence.name || 'Your analysis'}</strong><Badge tone={status.tone}>{status.label}</Badge></>}</div>
    <div className="results-tabs" role="tablist" aria-label="Analysis result sections">
      {TABS.map(([tab, label], index) => <button key={tab} className="results-tab" type="button" role="tab" id={`${id}-tab-${tab}`} aria-controls={`${id}-panel-${tab}`} aria-selected={active === tab} tabIndex={active === tab ? 0 : -1} ref={(node) => { tabRefs.current[index] = node; }} onClick={() => dispatchViewer({ type: 'set_tab', tab })} onKeyDown={(event) => navigateTabs(event, index)}>{label}</button>)}
    </div>
    {TABS.map(([tab, label]) => <div key={tab} className="results-content" role="tabpanel" id={`${id}-panel-${tab}`} aria-labelledby={`${id}-tab-${tab}`} hidden={active !== tab} tabIndex={0} aria-label={label}>{active === tab || tab === 'features' || tab === 'sequence' ? renderTab(tab) : null}</div>)}
  </div>;
}
