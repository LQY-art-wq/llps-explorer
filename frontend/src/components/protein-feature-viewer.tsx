'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { FeaturePlot } from './feature-plot';
import { domainLength, focusRegionDomain, focusResidueDomain, fullDomain, panDomain, zoomDomain } from '../lib/feature-coordinates.ts';
import type { ResidueDomain } from '../lib/feature-coordinates.ts';
import { getFeatureTooltip } from '../lib/feature-viewer-model.ts';
import type { FeatureRegion, FeatureTrack, FeatureViewerModel } from '../lib/feature-viewer-model.ts';
import { createFeatureViewState, updateFeatureView } from '../lib/feature-view-state.ts';
import type { FeatureViewAction } from '../lib/feature-view-state.ts';
import type { ViewerFocusRequest, ViewerRegionSelection } from '../lib/viewer-data.ts';

export interface FeaturePerformanceSample { kind: 'initial_render' | 'zoom' | 'hover'; durationMs: number }
export interface ProteinFeatureViewerProps {
  model: FeatureViewerModel;
  variant?: 'full' | 'compact';
  selectedResidue: number | null;
  selectedRegion: ViewerRegionSelection | null;
  focusRequest?: ViewerFocusRequest | null;
  onResidueSelect: (position: number) => void;
  onRegionSelect: (region: ViewerRegionSelection) => void;
  onSelectionClear: () => void;
  onOpenFull?: () => void;
  onViewInSequence?: () => void;
  onPerformance?: (sample: FeaturePerformanceSample) => void;
}

const shortLabels: Record<string, string> = {
  'lreca-attribution': 'LRECA Attribution', 'lreca-kde': 'LRECA KDE', 'lreca-critical': 'LRECA hotspots',
  'fuzdrop-propensity': 'FuzDrop pDP', 'fuzdrop-regions': 'FuzDrop regions', 'seg-regions': 'LCR — SEG',
  'dismeta-regions': 'IDR — DisMeta',
};
function numeric(value: number): string {
  // Rounding is for text only; these values never feed back into coordinates or results.
  return value !== 0 && Math.abs(value) < 0.001 ? value.toExponential(3) : value.toFixed(3);
}

export function ProteinFeatureViewer(props: ProteinFeatureViewerProps) {
  if (props.model.length < 1) return <section className="panel feature-viewer" aria-label="Protein Feature Viewer">
    <div className="panel-header"><h2>Protein Feature Viewer</h2><span className="badge">Awaiting analysis</span></div>
    <p className="muted">Run an analysis to align its available residue values and regions on a shared protein coordinate.</p>
    {props.model.issues.map((issue, index) => <p className="notice" key={index}>{issue.message}</p>)}
    <p className="feature-unavailable">IDR — DisMeta · Unavailable</p>
  </section>;
  return <FeatureViewerSession key={props.model.analysisId ?? 'unidentified-result'} {...props} />;
}

function FeatureViewerSession({ model, variant = 'full', selectedResidue, selectedRegion, focusRequest,
  onResidueSelect, onRegionSelect, onSelectionClear, onOpenFull, onViewInSequence, onPerformance }: ProteinFeatureViewerProps) {
  const compact = variant === 'compact';
  const [state, setState] = useState(() => createFeatureViewState(model.analysisId, model.length));
  const [cursor, setCursor] = useState<number | null>(null);
  const selectionKey = selectedResidue !== null ? `residue:${selectedResidue}`
    : selectedRegion ? `region:${selectedRegion.method}:${selectedRegion.id ?? selectedRegion.type ?? ''}:${selectedRegion.start}:${selectedRegion.end}` : null;
  const [observedSelection, setObservedSelection] = useState(selectionKey);
  const focusKey = focusRequest ? `${focusRequest.requestId}:${focusRequest.start}:${focusRequest.end}` : null;
  const [appliedFocus, setAppliedFocus] = useState<string | null>(null);
  const [inspectPosition, setInspectPosition] = useState('1');
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [regionPage, setRegionPage] = useState(0);
  const [mountStarted] = useState(() => performance.now());
  const initialReported = useRef(false);
  const measurements = useRef<{ kind: FeaturePerformanceSample['kind']; started: number }[]>([]);
  const performanceCallback = useRef(onPerformance);
  const id = useId();

  // An external selection updates the inspector, while the feature zoom stays independent.
  if (selectionKey !== observedSelection) {
    setObservedSelection(selectionKey);
    setCursor(selectedResidue ?? selectedRegion?.start ?? null);
  }

  // A guarded adjustment to this component's own state handles external focus synchronously.
  // Ordinary polling/hover never changes the focus key or resets a user's zoom.
  if (focusKey !== appliedFocus) {
    setAppliedFocus(focusKey);
    if (focusRequest && !compact) {
      const next = focusRequest.start === focusRequest.end
        ? focusResidueDomain(focusRequest.start, model.length)
        : focusRegionDomain(focusRequest, model.length);
      setState((previous) => updateFeatureView(previous, { type: 'domain', domain: next }, model.length));
      setCursor(Math.min(model.length, Math.max(1, focusRequest.start)));
    }
  }
  useEffect(() => { performanceCallback.current = onPerformance; }, [onPerformance]);
  const measure = useCallback((kind: FeaturePerformanceSample['kind']) => {
    if (!performanceCallback.current) return;
    measurements.current.push({ kind, started: performance.now() });
  }, []);
  // Measure application work through React's commit, independently of host/background
  // requestAnimationFrame throttling. Canvas drawing has a separate execution timer.
  useLayoutEffect(() => {
    if (!performanceCallback.current) return;
    if (!initialReported.current) {
      initialReported.current = true;
      performanceCallback.current({ kind: 'initial_render', durationMs: performance.now() - mountStarted });
    }
    const pending = measurements.current.splice(0);
    for (const item of pending) performanceCallback.current({ kind: item.kind, durationMs: performance.now() - item.started });
  });

  const change = useCallback((action: FeatureViewAction) => {
    if (action.type === 'domain' || action.type === 'reset') measure('zoom');
    setState((previous) => updateFeatureView(previous, action, model.length));
  }, [measure, model.length]);
  const changeDomain = useCallback((domain: ResidueDomain) => change({ type: 'domain', domain }), [change]);
  const hover = useCallback((position: number | null) => {
    if (position === cursor) return;
    if (position !== null) measure('hover');
    setCursor(position);
  }, [measure, cursor]);
  const selectResidue = useCallback((position: number) => {
    setCursor(position); onResidueSelect(position);
  }, [onResidueSelect]);
  const selectRegion = useCallback((region: ViewerRegionSelection) => {
    onRegionSelect(region); setCursor(region.start);
    if (!compact) changeDomain(focusRegionDomain(region, model.length));
  }, [onRegionSelect, compact, changeDomain, model.length]);
  const domain = compact ? fullDomain(model.length) : state.domain;
  const tracks = useMemo(() => model.tracks.filter((track) => compact
    ? track.id !== 'lreca-kde' && track.id !== 'fuzdrop-regions'
    : !state.hiddenTrackIds.includes(track.id)), [model.tracks, compact, state.hiddenTrackIds]);
  const allRegions = useMemo(() => model.tracks.flatMap((track) => track.kind === 'region' ? track.regions : []), [model.tracks]);
  const region = selectedRegion ? allRegions.find((item) => selectedRegion.id ? item.id === selectedRegion.id
    : item.method === selectedRegion.method && item.start === selectedRegion.start && item.end === selectedRegion.end
      && (!selectedRegion.type || item.type === selectedRegion.type)) : null;
  const inspected = cursor ?? selectedResidue ?? selectedRegion?.start ?? null;
  const tooltip = inspected === null ? null : getFeatureTooltip(model, inspected);
  const span = domainLength(domain);
  const scope = `${domain.start.toLocaleString()}–${domain.end.toLocaleString()}`;
  const page = Math.min(regionPage, Math.max(0, Math.ceil(allRegions.length / 20) - 1));

  function focusPosition(event: FormEvent) {
    event.preventDefault();
    const position = Number(inspectPosition);
    if (!Number.isSafeInteger(position) || position < 1 || position > model.length) {
      setInspectError(`Enter a residue position from 1 to ${model.length}.`); return;
    }
    setInspectError(null); selectResidue(position); changeDomain(focusResidueDomain(position, model.length));
  }

  return <section className={`panel feature-viewer ${compact ? 'is-compact' : ''}`} aria-label={compact ? 'Protein Feature Viewer overview' : 'Protein Feature Viewer'}
    data-analysis-id={model.analysisId ?? ''} data-visible-start={domain.start} data-visible-end={domain.end}>
    <div className="panel-header feature-heading"><div><p className="eyebrow">ALIGNED PROTEIN FEATURES</p><h2>Protein Feature Viewer</h2></div>
      <span className="badge">{compact ? 'Full-length overview' : `${tracks.length} visible tracks`}</span></div>
    <p className="muted small">One residue coordinate. Distinct evidence types. <strong>1–{model.length.toLocaleString()} aa</strong>.</p>
    {model.issues.length > 0 && <ul className="notice feature-issues" aria-label="Feature data validation issues">
      {model.issues.map((issue, index) => <li key={`${issue.outputId}-${index}`}>{issue.message}</li>)}</ul>}

    {!compact && <>
      <div className="feature-toolbar" role="group" aria-label="Feature viewer controls">
        <div className="feature-toolbar-cluster">
          <button className="button" type="button" aria-label="Zoom in" disabled={span <= 1} onClick={() => changeDomain(zoomDomain(domain, model.length, 0.5, inspected ?? undefined))}>＋</button>
          <button className="button" type="button" aria-label="Zoom out" disabled={span >= model.length} onClick={() => changeDomain(zoomDomain(domain, model.length, 2, inspected ?? undefined))}>−</button>
          <button className="button" type="button" onClick={() => change({ type: 'reset' })}>Reset zoom</button>
        </div>
        <fieldset className="feature-mode"><legend className="sr-only">Drag interaction</legend>
          <label><input type="radio" name={`${id}-drag`} checked={state.interactionMode === 'pan'} onChange={() => change({ type: 'mode', mode: 'pan' })} />Pan</label>
          <label><input type="radio" name={`${id}-drag`} checked={state.interactionMode === 'select'} onChange={() => change({ type: 'mode', mode: 'select' })} />Select range</label>
        </fieldset>
        <details className="feature-track-menu"><summary className="button">Tracks <span className="muted">{tracks.length}/{model.tracks.length}</span></summary>
          <fieldset><legend>Visible data tracks</legend>{model.tracks.map((track) => <label key={track.id}>
            <input type="checkbox" checked={!state.hiddenTrackIds.includes(track.id)} onChange={() => change({ type: 'toggle', id: track.id })} />{track.label}</label>)}
            {!model.tracks.length && <p>No drawable output in this analysis.</p>}<p className="muted small">The protein coordinate always stays visible.</p></fieldset>
        </details>
        <form className="feature-inspect-form" onSubmit={focusPosition} noValidate><label htmlFor={`${id}-position`}>Residue</label>
          <input className="input" id={`${id}-position`} aria-label="Residue to focus" type="number" min={1} max={model.length} step={1} value={inspectPosition} onChange={(event) => setInspectPosition(event.target.value)} />
          <button className="button" type="submit">Focus residue</button></form>
      </div>
      {inspectError && <p className="validation-message invalid" role="alert">{inspectError}</p>}
      <RangeForm domain={domain} length={model.length} onChange={changeDomain} />
      <p className="feature-interaction-hint" id={`${id}-help`}>Wheel or trackpad to zoom · Drag to {state.interactionMode === 'pan' ? 'pan' : 'select a range'} · Click a residue or region · Arrow keys and Enter are supported on the plot.</p>
    </>}

    <FeaturePlot model={model} tracks={tracks} domain={domain} cursor={cursor} selectedResidue={selectedResidue}
      selectedRegion={selectedRegion} interactionMode={state.interactionMode} onHover={hover}
      onResidueSelect={selectResidue} onRegionSelect={selectRegion} onDomainChange={changeDomain} compact={compact} />
    {!model.tracks.length && <p className="feature-no-tracks">No drawable tracks are available for this result. Method and output states are listed below.</p>}

    {!compact && <div className="feature-navigator" role="group" aria-label="Shared coordinate navigator">
      <div className="feature-nav-heading"><strong>Visible residues <output aria-live="polite">{scope}</output></strong><span className="muted">{span.toLocaleString()} of {model.length.toLocaleString()} aa</span></div>
      <div className="feature-nav-window" aria-hidden="true"><span style={{ left: `${(domain.start - 1) / model.length * 100}%`, width: `${span / model.length * 100}%` }} /></div>
      <div className="feature-nav-controls"><button className="button" type="button" aria-label="Pan left" disabled={domain.start <= 1} onClick={() => changeDomain(panDomain(domain, model.length, -Math.max(1, span / 4)))}>←</button>
        <label>Start<input aria-label="Navigator start" type="range" min={1} max={model.length} step={1} value={domain.start} onChange={(event) => changeDomain({ start: Math.min(Number(event.target.value), domain.end), end: domain.end })} /></label>
        <label>End<input aria-label="Navigator end" type="range" min={1} max={model.length} step={1} value={domain.end} onChange={(event) => changeDomain({ start: domain.start, end: Math.max(Number(event.target.value), domain.start) })} /></label>
        <button className="button" type="button" aria-label="Pan right" disabled={domain.end >= model.length} onClick={() => changeDomain(panDomain(domain, model.length, Math.max(1, span / 4)))}>→</button></div>
    </div>}

    <FeatureLegend tracks={model.tracks} />
    <div className="feature-output-notes">{model.outputStates.filter((output) => !['success'].includes(output.status)).map((output) =>
      <span key={output.id} data-output-id={output.id} data-output-status={output.status} title={output.message}>
        <strong>{shortLabels[output.id]}</strong> · {output.message}</span>)}</div>

    {!compact && <>
      <section className="feature-inspector" aria-label="Shared residue tooltip" data-position={tooltip?.position ?? ''}>
        <div className="feature-inspector-heading"><div><span className="eyebrow">RESIDUE INSPECTOR</span><h3>{tooltip ? <>Position <strong>{tooltip.position}</strong><span className="feature-aa">{tooltip.aa}</span></> : 'Inspect aligned evidence'}</h3></div>
          <div className="button-group">
            {selectedResidue !== null && onViewInSequence && <button className="button" type="button" onClick={onViewInSequence}>View in Sequence</button>}
            <button className="text-button" type="button" disabled={selectedResidue === null && selectedRegion === null} onClick={() => { setCursor(null); onSelectionClear(); }}>Clear selection</button>
          </div></div>
        {tooltip ? <dl className="feature-tooltip-grid">{tooltip.rows.map((row) => <div key={row.id} data-tooltip-track={row.id} data-value-status={row.status}>
          <dt>{shortLabels[row.id]}</dt><dd title={row.value === null ? undefined : String(row.value)}>{row.value !== null ? numeric(row.value) : row.text ?? 'N/A'}
            {row.regions.length > 0 && <span className="feature-membership">{row.regions.map((item) => `${item.isPrimary ? 'Primary hotspot' : item.label} ${item.start}–${item.end} (${item.length} aa)`).join('; ')}</span>}</dd></div>)}</dl>
          : <p className="muted small">Move across a track, focus the plot and use arrow keys, or enter a residue position. A single guideline aligns every visible track.</p>}
      </section>
      <div className="feature-selection-status" role="status" aria-live="polite">{selectedResidue !== null ? `Selected residue: ${selectedResidue}${model.sequence ? ` (${model.sequence[selectedResidue - 1]})` : ''}`
        : region ? `Selected ${region.method.toUpperCase()} region: ${region.start}–${region.end}` : 'No fixed selection'}</div>
      {region && <RegionDetails region={region} onViewInSequence={onViewInSequence} />}
      {allRegions.length > 0 && <details className="feature-region-list"><summary>Region table · {allRegions.length} native regions</summary>
        <div className="table-scroll"><table><caption className="sr-only">Native feature regions. Endpoints are 1-based inclusive; activate a region to focus it.</caption><thead><tr><th scope="col">Method</th><th scope="col">Type</th><th scope="col">Region</th><th scope="col">Length</th></tr></thead><tbody>
          {allRegions.slice(page * 20, page * 20 + 20).map((item) => <tr key={item.id}><td>{item.method.toUpperCase()}</td><td>{item.isPrimary ? 'Primary hotspot' : item.label}</td>
            <td><button className="table-link" type="button" onClick={() => selectRegion(item)} aria-label={`Select ${item.method.toUpperCase()} region ${item.start} to ${item.end}`}>{item.start}–{item.end}</button></td><td>{item.length} aa</td></tr>)}</tbody></table></div>
        {allRegions.length > 20 && <div className="table-pagination"><button className="button" type="button" disabled={page === 0} onClick={() => setRegionPage(page - 1)}>Previous regions</button><span>Page {page + 1} of {Math.ceil(allRegions.length / 20)}</span><button className="button" type="button" disabled={(page + 1) * 20 >= allRegions.length} onClick={() => setRegionPage(page + 1)}>Next regions</button></div>}
      </details>}
      <p className="muted small feature-science-note">Attribution explains the model; KDE is backend contribution density; FuzDrop pDP is imported propensity; SEG is a region annotation. Values and native boundaries are never recomputed here.</p>
    </>}
    {compact && onOpenFull && <button className="button feature-open-full" type="button" onClick={onOpenFull}>Open full feature viewer <span aria-hidden="true">→</span></button>}
  </section>;
}

function RangeForm({ domain, length, onChange }: { domain: ResidueDomain; length: number; onChange: (domain: ResidueDomain) => void }) {
  const key = `${domain.start}:${domain.end}`;
  const [draft, setDraft] = useState({ key, start: String(domain.start), end: String(domain.end), error: '' });
  if (draft.key !== key) setDraft({ key, start: String(domain.start), end: String(domain.end), error: '' });
  const id = useId();
  function apply(event: FormEvent) {
    event.preventDefault();
    const start = Number(draft.start), end = Number(draft.end);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end > length || start > end) {
      setDraft({ ...draft, error: `Use an inclusive range within 1–${length}, with start ≤ end.` }); return;
    }
    setDraft({ ...draft, error: '' }); onChange({ start, end });
  }
  return <form className="feature-range-form" onSubmit={apply} noValidate>
    <label htmlFor={`${id}-start`}>Visible start</label><input className="input" id={`${id}-start`} type="number" min={1} max={length} step={1} value={draft.start} onChange={(event) => setDraft({ ...draft, start: event.target.value })} />
    <label htmlFor={`${id}-end`}>Visible end</label><input className="input" id={`${id}-end`} type="number" min={1} max={length} step={1} value={draft.end} onChange={(event) => setDraft({ ...draft, end: event.target.value })} />
    <button className="button" type="submit">Apply range</button><span className="muted small">1-based · inclusive</span>
    {draft.error && <span className="validation-message invalid" role="alert">{draft.error}</span>}
  </form>;
}
function FeatureLegend({ tracks }: { tracks: FeatureTrack[] }) {
  return <div className="feature-legend" aria-label="Feature legend">{tracks.map((track) => <span key={track.id} data-method={track.method}>
    <i className={`feature-swatch ${track.kind === 'region' ? 'is-region' : ''} ${track.id === 'lreca-kde' ? 'is-kde' : ''}`} aria-hidden="true" />{shortLabels[track.id]}</span>)}
    {tracks.some((track) => track.id === 'lreca-critical') && <><span><i className="feature-primary-key" aria-hidden="true" />Primary hotspot</span><span><i className="feature-candidate-key" aria-hidden="true" />Candidate hotspot</span></>}
  </div>;
}
function RegionDetails({ region, onViewInSequence }: { region: FeatureRegion; onViewInSequence?: () => void }) {
  return <section className="feature-region-details" aria-label="Selected region details"><h3>{region.isPrimary ? 'Primary hotspot' : region.label}</h3><dl>
    <div><dt>Method</dt><dd>{region.method.toUpperCase()}</dd></div><div><dt>Region type</dt><dd>{region.label}</dd></div>
    <div><dt>Start</dt><dd>{region.start}</dd></div><div><dt>End</dt><dd>{region.end}</dd></div><div><dt>Length</dt><dd>{region.length} aa</dd></div>
    {typeof region.score === 'number' && <div><dt>Cumulative KDE score</dt><dd title={String(region.score)}>{numeric(region.score)}</dd></div>}
    {typeof region.isPrimary === 'boolean' && <div><dt>Backend selection</dt><dd>{region.isPrimary ? 'Primary hotspot' : 'Candidate hotspot'}</dd></div>}
  </dl>{onViewInSequence && <button className="button" type="button" onClick={onViewInSequence}>View in Sequence</button>}</section>;
}
